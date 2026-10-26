#!/usr/bin/env python3
# Simple GUI for building a custom vPilot VMR file on top of the IVAO MTL.
# Copyright 2024-2026 create-ivao-vmr contributors. Licensed under the Apache License, Version 2.0; see LICENSE and NOTICE.
#
# Run it from the IVAO MTL folder (Packages/Community/IVAO_MTL), the same place as create_vmr.py:
#   python vmr_gui.py
# It starts a small local web server (standard library only) and shows the GUI in its own window
# (through pywebview, "pip install pywebview"; without it the GUI opens in your browser instead).
# In the GUI you can:
#   - turn on ready-made rule sets from the "presets" folder (for example the Smartwings group),
#   - add your own ModelMatchRule lines (CallsignPrefix / TypeCode / ModelName, "//" for alternatives),
#   - add the rules generated from your MTL (the same rules create_vmr.py makes, all liveries or the
#     standard liveries only) after your own rules, so that one VMR file is enough in vPilot,
#   - save the result as a VMR file.
# Every livery shows its picture from the MTL catalog (https://mtl.ivao.aero/catalog) and links to its page
# there. The pictures are downloaded once into the "previews" folder next to the program.
# The settings of the last run (VMR name, its folder, ticked presets, MTL choice) are kept in
# vmr_gui_settings.json next to the program.
#
# Options:
#   -d | --directory [path]   folder that contains SimObjects/Airplanes (default: the current folder)
#   -p | --output-directory   folder where generated VMR files are saved (default: the folder of the last
#                             saved VMR, the first time the current folder)
#   --port [number]           port of the local server (default: 8765)
#   --browser                 show the GUI in the web browser instead of its own window
#   --no-browser              only run the server, do not open a window or a browser

import argparse
import configparser
import json
import mimetypes
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# The rules that turn the liveries into a VMR (airline code, aircraft type, standard or special livery,
# grouping) are shared with create_vmr.py, so the GUI and the script produce the same VMRs.
from create_vmr import group_rules, is_standard_livery, mtl_airline_code, mtl_type_code, xml_attr

# When packed into an .exe with PyInstaller (see build_exe.spec), the gui and presets folders are bundled
# inside the executable and unpacked to a temporary folder (sys._MEIPASS). Files the user edits or that
# the GUI writes (own presets, the settings, the generated VMRs) live next to the .exe instead.
FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
GUI_DIR = BUNDLE_DIR / "gui"
PRESETS_DIRS = [BUNDLE_DIR / "presets", APP_DIR / "presets"]  # a preset next to the exe replaces a bundled one of the same name
LOG_FILE = APP_DIR / "vmr_gui.log"
# The script works in the folder it is run from, like create_vmr.py. The .exe works in its own folder,
# because Windows does not always start a double-clicked program in the folder it lies in.
DEFAULT_DIR = str(APP_DIR) if FROZEN else "."
# Set by the build workflow: open the window, close it again after a few seconds and exit.
SELF_TEST = os.environ.get("IVAO_VMR_GUI_SELFTEST") == "1"

# Page of a livery in the MTL catalog (https://mtl.ivao.aero/catalog).
CATALOG_SEARCH = "https://mtl.ivao.aero/catalog?textureName={name}"
# Picture of a livery in the MTL catalog. The thumbnails inside the MTL packages are one generic picture
# for every livery, but the MTL Installer writes an "ivao.ini" into every texture folder it installs, and
# its "mtl_version" is the number of the livery in the catalog. With it the catalog picture can be
# downloaded without an API key. The pictures are kept in the "previews" folder next to the program, so
# that each one is downloaded only once.
CATALOG_IMAGE = "https://download.ivao.aero/v2/aircraftsTextures/{id}/files/latest/image"
PREVIEWS_DIR = APP_DIR / "previews"
TEXTURE_INFO_FILE = "ivao.ini"
# The MTL Installer also keeps a list of every livery in mtl.dat in the MTL folder, one line per livery:
# "A320AAF,Aigle Azur (AAF),0.0,0.0,11636" (MTL id, catalog name, two numbers, catalog number). It is used
# for the catalog number of liveries whose texture folder has no ivao.ini.
MTL_DAT_FILE = "mtl.dat"
BROKEN_VERSION_LINE = re.compile(r"^([ \t]*)VERSION\](?=[ \t]*\r?$)", re.MULTILINE)

# The settings of the last run (VMR name, folder of the last saved VMR, ticked presets and MTL choice).
# See the "Settings" section below for how the file stays compatible between versions.
SETTINGS_FILE = APP_DIR / "vmr_gui_settings.json"


def read_app_version():
    """The version of this program. The build writes it into version.txt inside the .exe (see build_exe.spec);
    running from source it is "dev"."""
    try:
        return (BUNDLE_DIR / "version.txt").read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


APP_VERSION = read_app_version()


# --------------------------------------------------------------------------------------------------
# VMR reading and writing
# --------------------------------------------------------------------------------------------------

def parse_vmr(text):
    """Returns the ModelMatchRule entries of a VMR file as a list of dicts with callsign (CallsignPrefix),
    type, models (list of ModelName alternatives) and, only when the rule has them, exactCallsign
    (Callsign: the whole callsign must match) and flightNumbers (FlightNumberRange, e.g. "4439-4858")."""
    rules = []
    # Some hand-made VMR files are not well-formed XML (missing closing tag, comment after the root).
    # Try the XML parser first and fall back to a regular expression that only looks at the rules.
    try:
        root = ET.fromstring(text.strip())
        for rule in root.iter("ModelMatchRule"):
            rules.append(_make_rule(rule.attrib))
        return rules
    except ET.ParseError:
        pass
    for match in re.finditer(r"<ModelMatchRule\b([^>]*)/?>", text):
        attrs = dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', match.group(1)))
        rules.append(_make_rule({k: _xml_unescape(v) for k, v in attrs.items()}))
    return rules


def _make_rule(attrs):
    rule = {
        "callsign": attrs.get("CallsignPrefix", "").strip().upper(),
        "type": attrs.get("TypeCode", "").strip().upper(),
        "models": [m.strip() for m in attrs.get("ModelName", "").split("//") if m.strip()],
    }
    # Without these the rule would be imported as a much broader one (a rule for one callsign would
    # become a rule for every aircraft of that type).
    if attrs.get("Callsign", "").strip():
        rule["exactCallsign"] = attrs["Callsign"].strip().upper()
    if attrs.get("FlightNumberRange", "").strip():
        rule["flightNumbers"] = attrs["FlightNumberRange"].strip()
    return rule


def _xml_unescape(value):
    return value.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&apos;", "'").replace("&amp;", "&")


def build_vmr(rules, comment=None):
    """Builds the text of a VMR file from a list of rules (see parse_vmr for the format).
    gui/app.js has the same function (buildVmr) for the preview and the "Save as" file; keep both alike."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<ModelMatchRuleSet>"]
    for rule in rules:
        if not rule.get("type") or not rule.get("models"):
            continue
        attrs = ""
        if rule.get("callsign"):
            attrs += ' CallsignPrefix="%s"' % xml_attr(rule["callsign"])
        if rule.get("exactCallsign"):
            attrs += ' Callsign="%s"' % xml_attr(rule["exactCallsign"])
        if rule.get("flightNumbers"):
            attrs += ' FlightNumberRange="%s"' % xml_attr(rule["flightNumbers"])
        attrs += ' TypeCode="%s" ModelName="%s"' % (xml_attr(rule["type"]), xml_attr("//".join(rule["models"])))
        lines.append("<ModelMatchRule%s />" % attrs)
    lines.append("</ModelMatchRuleSet>")
    if comment:
        lines.append("<!-- %s -->" % comment.replace("--", "- -"))
    lines.append("<!-- VMR created by create-ivao-vmr GUI https://github.com/vojta48/create-ivao-vmr -->")
    return "\r\n".join(lines) + "\r\n"


def list_presets():
    files = {}
    for folder in PRESETS_DIRS:
        if folder.is_dir():
            for path in folder.glob("*.vmr"):
                files[path.stem] = path
    presets = []
    for path in sorted(files.values(), key=lambda p: p.stem.lower()):
        text = _read_text(path)
        description = ""
        comment = re.search(r"<!--(.*?)-->", text, re.S)
        if comment:
            description = " ".join(comment.group(1).split())
        presets.append({
            "id": path.stem,
            "name": path.stem.replace("_", " "),
            "file": path.name,
            "description": description,
            "rules": parse_vmr(text),
        })
    return presets


def _read_text(path):
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------------------------------
# Liveries installed in the MTL
# --------------------------------------------------------------------------------------------------

class Library:
    """The liveries found in SimObjects/Airplanes of the MTL, keyed by their title (the MTL id, e.g. A320TVS)."""

    def __init__(self, models_root):
        self.models_root = Path(models_root)
        self.airplanes = self.models_root / "SimObjects" / "Airplanes"
        self.liveries = {}
        self.errors = []
        self.scanned = False

    def scan(self):
        self.liveries = {}
        self.errors = []
        self.catalog_ids = read_mtl_dat(self.models_root / MTL_DAT_FILE)
        if self.airplanes.is_dir():
            for model_dir in sorted(self.airplanes.iterdir(), key=lambda p: p.name):  # the order create_vmr.py uses
                cfg = model_dir / "aircraft.cfg"
                if cfg.is_file():
                    self._read_cfg(model_dir, cfg)
        self.scanned = True
        return self

    def _read_cfg(self, model_dir, cfg):
        # texture="TVS" in aircraft.cfg means the folder texture.TVS, but Windows does not care about case
        folders = {}
        try:
            for child in model_dir.iterdir():
                if child.name.lower().startswith("texture.") and child.is_dir():
                    folders[child.name[len("texture."):].lower()] = child
        except OSError:
            pass
        config = configparser.ConfigParser(strict=False, interpolation=None)
        try:
            # The broken "VERSION]" header that create_vmr.py repairs in the file (see fix_version_section
            # there) is repaired here in memory only: the GUI does not change the MTL.
            text = BROKEN_VERSION_LINE.sub(r"\1[VERSION]", _read_text(cfg))
            config.read_string(text, source=str(cfg))
        except (configparser.Error, OSError) as err:
            self.errors.append("%s: %s" % (cfg, err))
        for section in config.sections():
            if "fltsim" not in section.lower():
                continue
            entry = config[section]
            title = _unquote(entry.get("title", ""))
            type_code = mtl_type_code(entry.get("ui_type", ""))
            # The same liveries create_vmr.py skips (see create_model_list there), with the same reasons.
            problem = None
            if not type_code:
                problem = "has an empty aircraft type"
            elif not title:
                problem = "has no title"
            elif title in self.liveries:
                problem = "uses the title %s, which another livery already uses" % title
            if problem:
                self.errors.append("%s [%s] %s, skipped." % (cfg, section, problem))
                continue
            texture = _unquote(entry.get("texture", ""))
            name = _unquote(entry.get("ui_variation", ""))
            airline = mtl_airline_code(texture, name, type_code)
            self.liveries[title] = {
                "id": title,
                "airline": airline or "",
                # False for liveries without an airline code a callsign can start with (ZZZ, "@xx"): the rules
                # generated from the MTL leave them out (see mtl_airline_code in create_vmr.py).
                "inVmr": airline is not None,
                "type": type_code,
                "texture": texture,
                "name": name,
                "model": model_dir.name,
                "standard": is_standard_livery(texture, name),
                "catalogId": read_catalog_id(folders.get(texture.lower())) or self.catalog_ids.get(title),
            }

    def summary(self):
        return list(self.liveries.values())

    def _model_list(self):
        """The liveries in the form create_vmr.py groups them: model_list[airline][type] = [MTL ids]."""
        model_list = {}
        for livery in self.liveries.values():
            if livery["type"] and livery["inVmr"]:
                model_list.setdefault(livery["airline"], {}).setdefault(livery["type"], []).append(livery["id"])
        return model_list

    def _special(self):
        return {l["id"] for l in self.liveries.values() if not l["standard"]}

    def mtl_rules(self, standard_only):
        """The rules create_vmr.py generates from the MTL (see group_rules there): one rule per airline and
        aircraft type with all its liveries as alternatives, with standard_only the standard liveries only."""
        return [{"callsign": airline, "type": type_code, "models": models}
                for airline, type_code, models, kept in group_rules(self._model_list(), self._special(), standard_only)]


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return value.strip()


# --------------------------------------------------------------------------------------------------
# Livery pictures from the MTL catalog
# --------------------------------------------------------------------------------------------------

def read_catalog_id(texture_dir):
    """The number of a livery in the MTL catalog, from the ivao.ini the MTL Installer put into its
    texture folder ("[IVAO] mtl_version = 18552"). None when the folder was not installed by the installer."""
    if texture_dir is None:
        return None
    info = texture_dir / TEXTURE_INFO_FILE
    try:
        text = info.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    match = re.search(r"^\s*mtl_version\s*=\s*(\d+)\s*$", text, re.MULTILINE | re.IGNORECASE)
    return int(match.group(1)) if match else None


def read_mtl_dat(path):
    """MTL id -> catalog number from the mtl.dat of the MTL Installer. Empty when there is no such file."""
    ids = {}
    try:
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ids
    for line in text.splitlines():
        # the catalog name can contain commas, the catalog number is always the last field
        mtl_id, _, rest = line.partition(",")
        number = rest.rpartition(",")[2].strip()
        if mtl_id.strip() and number.isdigit():
            ids[mtl_id.strip()] = int(number)
    return ids


class Previews:
    """Downloads the catalog picture of a livery once and keeps it in the previews folder."""

    EXTENSIONS = {"image/png": ".png", "image/webp": ".webp", "image/jpeg": ".jpg", "image/gif": ".gif"}

    def __init__(self, folder):
        self.folder = Path(folder)
        self.failed = {}  # catalog id -> error text, so that an unreachable picture is not tried over and over
        self.lock = threading.Lock()
        self.locks = {}  # catalog id -> lock, so that two requests for the same picture download it once
        self.downloads = threading.BoundedSemaphore(4)  # at most four downloads at a time

    def cached(self, catalog_id):
        for ext in self.EXTENSIONS.values():
            path = self.folder / ("%d%s" % (catalog_id, ext))
            if path.is_file():
                return path
        return None

    def get(self, catalog_id):
        """The picture file of a livery, or None when it is not available (no network, not in the catalog)."""
        path = self.cached(catalog_id)
        if path:
            return path
        with self.lock:
            if catalog_id in self.failed:
                return None
            lock = self.locks.setdefault(catalog_id, threading.Lock())
        with lock:
            path = self.cached(catalog_id)
            if path:
                return path
            try:
                with self.downloads:
                    path = self._download(catalog_id)
            except (urllib.error.URLError, OSError, ValueError) as err:
                with self.lock:
                    self.failed[catalog_id] = str(err)
                print("Catalog picture %d not available: %s" % (catalog_id, err))
                return None
        return path

    def _download(self, catalog_id):
        request = urllib.request.Request(CATALOG_IMAGE.format(id=catalog_id), headers={"User-Agent": "create-ivao-vmr GUI"})
        with urllib.request.urlopen(request, timeout=20) as response:
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type not in self.EXTENSIONS:
                raise ValueError("not a picture (%s)" % (content_type or "no content type"))
            data = response.read()
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / ("%d%s" % (catalog_id, self.EXTENSIONS[content_type]))
        temp = path.with_name(path.name + ".part")
        temp.write_bytes(data)
        temp.replace(path)
        return path


# --------------------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------------------
#
# The settings of the last run are kept in vmr_gui_settings.json next to the program, for example:
#   {"settingsVersion": 1, "createdBy": "1.2.0", "savedBy": "1.3.0", "fileName": "my rules.vmr",
#    "lastFolder": "C:\\Users\\me\\Documents\\vPilot Files", "selectedPresets": ["smartwings_group"],
#    "mtlRules": {"enabled": true, "mode": "standard"}}
# createdBy and savedBy are the program versions that created the file and wrote it last; they are only
# information. Whether a file can be used is decided by settingsVersion, the version of the file format, so
# that a new program version keeps the settings of the previous one:
#   - A new setting does not change the format: a file without it gets the default for it.
#   - A value that is missing or not valid falls back to its default; the other settings are kept.
#   - Settings this version does not know (from a newer version) are kept when the file is written.
# Only a change that old files cannot follow raises SETTINGS_VERSION, and OLDEST_SUPPORTED_SETTINGS_VERSION
# when an old file must not be used any more. Such a file, and a file that cannot be read at all, is deleted
# and the settings start from the defaults; the GUI shows a message about it once.
SETTINGS_VERSION = 1
OLDEST_SUPPORTED_SETTINGS_VERSION = 1
MTL_MODES = ("standard", "all")


def _file_name_setting(value):
    name = Path(str(value).strip()).name
    if not isinstance(value, str) or not name or len(name) > 255:
        raise ValueError(value)
    return name


def _folder_setting(value):
    if not isinstance(value, str):
        raise ValueError(value)
    return value.strip()


def _presets_setting(value):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(value)
    return list(dict.fromkeys(value))  # without duplicates, in their order


def _mtl_setting(value):
    if not isinstance(value, dict):
        raise ValueError(value)
    enabled, mode = value.get("enabled", False), value.get("mode", "standard")
    if not isinstance(enabled, bool) or mode not in MTL_MODES:
        raise ValueError(value)
    return {"enabled": enabled, "mode": mode}


# Every setting with its default and the function that checks (and cleans) a value read from the file.
SETTINGS = {
    "fileName": ("custom.vmr", _file_name_setting),
    "lastFolder": ("", _folder_setting),
    "selectedPresets": ([], _presets_setting),
    "mtlRules": ({"enabled": False, "mode": "standard"}, _mtl_setting),
}


def default_settings():
    return json.loads(json.dumps({key: default for key, (default, check) in SETTINGS.items()}))  # a deep copy


class Settings:
    """The settings of the last run. path None keeps them in memory only (used by the tests)."""

    def __init__(self, path):
        self.path = Path(path) if path else None
        self.file = {}            # what the file contains, kept so that unknown settings survive a write
        self.values = default_settings()
        self.notice = None        # the message for the GUI when the file had to be deleted
        self.lock = threading.Lock()

    def load(self):
        if self.path is None or not self.path.is_file():
            return self
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or not isinstance(data.get("settingsVersion"), int) or isinstance(data.get("settingsVersion"), bool):
                raise ValueError("not a settings file of the IVAO VMR generator")
        except (OSError, ValueError) as err:
            return self._reset("Your settings file could not be read (%s)." % err)
        if data["settingsVersion"] < OLDEST_SUPPORTED_SETTINGS_VERSION:
            return self._reset("Your settings file was created by version %s of the IVAO VMR generator, which this version (%s) "
                               "no longer supports." % (data.get("createdBy") or "unknown", APP_VERSION))
        self.file = data
        for key, (default, check) in SETTINGS.items():
            if key in data:
                try:
                    self.values[key] = check(data[key])
                except ValueError:
                    print("  Settings: the value of %s is not valid, using the default." % key)
        return self

    def _reset(self, reason):
        try:
            self.path.unlink()
        except OSError:
            pass
        self.file, self.values = {}, default_settings()
        self.notice = reason + " It was deleted, and the settings were reset to the defaults."
        print("  " + self.notice)
        return self

    def take_notice(self):
        """The message about a deleted settings file, given out only once."""
        notice, self.notice = self.notice, None
        return notice

    def update(self, changes):
        """Takes over the valid known settings in changes and writes the file. Returns the settings."""
        with self.lock:
            for key, value in changes.items():
                if key in SETTINGS:
                    try:
                        self.values[key] = SETTINGS[key][1](value)
                    except ValueError:
                        pass
            self._write()
            return dict(self.values)

    def _write(self):
        if self.path is None:
            return
        # the versions first, so that they are the first thing one sees in the file
        data = {"settingsVersion": None, "createdBy": None, "savedBy": None}
        data.update(self.file)
        for key, value in self.values.items():
            # inside a group of settings, the parts this version does not know are kept as well
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                value = dict(data[key], **value)
            data[key] = value
        # a file written by a newer version keeps its format version, so that version can still read it
        data["settingsVersion"] = max(self.file.get("settingsVersion", 0), SETTINGS_VERSION)
        data["createdBy"] = self.file.get("createdBy") or APP_VERSION
        data["savedBy"] = APP_VERSION
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(self.path.name + ".part")
            temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            temp.replace(self.path)
            self.file = data
        except OSError as err:
            # the settings must never stop the program from working
            print("  Settings could not be saved to %s: %s" % (self.path, err))


# --------------------------------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------------------------------

class App:
    def __init__(self, models_root, output_dir=None, settings=None):
        """output_dir None: the folder of the last saved VMR (from the settings), or DEFAULT_DIR. A folder given
        on the command line (-p) always wins and is kept for the whole run."""
        self.library = Library(models_root)
        self.settings = settings or Settings(None)
        self.fixed_output_dir = output_dir is not None
        last = self.settings.values["lastFolder"]
        if output_dir is None:
            output_dir = last if last and Path(last).is_dir() else DEFAULT_DIR
        self.output_dir = Path(output_dir)
        self.previews = Previews(PREVIEWS_DIR)
        self.scan_lock = threading.Lock()

    def saved(self, path):
        """Remembers where a VMR was saved: the next VMR goes to the same folder, under the same name."""
        path = Path(path).resolve()
        if not self.fixed_output_dir:
            self.output_dir = path.parent
        self.settings.update({"lastFolder": str(path.parent), "fileName": path.name})

    def scanned_library(self):
        """The library, scanned on first use by whichever request needs it first (the server answers
        several requests at a time, the lock keeps it to one scan)."""
        with self.scan_lock:
            if not self.library.scanned:
                self.library.scan()
        return self.library


class Handler(BaseHTTPRequestHandler):
    app = None  # set in main()

    def log_message(self, fmt, *args):
        pass

    # ----- helpers -----
    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, cache=False):
        path = Path(path)
        if not path.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length > 0 else b""

    def from_this_computer(self):
        """The server only answers the GUI itself. A web page from elsewhere that the user has open could
        otherwise send requests to it: the Host header stops pages that point their own domain name at
        127.0.0.1 (DNS rebinding), and a POST must be JSON, which a browser only sends cross-site after
        asking the server first (a CORS preflight, which this server never allows)."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            self.send_error(403)
            return False
        return True

    # ----- routing -----
    def do_GET(self):
        if not self.from_this_computer():
            return
        path = urllib.parse.urlparse(self.path).path
        app = self.app
        if path in ("/", "/index.html"):
            self.send_file(GUI_DIR / "index.html")
        elif path.startswith("/static/"):
            name = Path(path[len("/static/"):]).name
            self.send_file(GUI_DIR / name)
        elif path == "/api/state":
            app.scanned_library()
            self.send_json({
                "modelsRoot": str(app.library.models_root),
                "airplanesFolder": str(app.library.airplanes),
                "libraryFound": app.library.airplanes.is_dir(),
                "outputDir": str(app.output_dir),
                "liveries": app.library.summary(),
                "errors": app.library.errors,
                "presets": list_presets(),
                "mtlRules": {"all": app.library.mtl_rules(False), "standard": app.library.mtl_rules(True)},
                "catalogSearch": CATALOG_SEARCH,
                "previewsDir": str(PREVIEWS_DIR),
                "version": APP_VERSION,
                "settings": app.settings.values,
                "settingsNotice": app.settings.take_notice(),
            })
        elif path == "/api/rescan":
            app.library.scan()
            self.send_json({
                "liveries": app.library.summary(),
                "errors": app.library.errors,
                "mtlRules": {"all": app.library.mtl_rules(False), "standard": app.library.mtl_rules(True)},
            })
        elif path.startswith("/api/preview/"):
            # the catalog picture of a livery (downloaded on first use, then served from the previews folder)
            livery = app.scanned_library().liveries.get(urllib.parse.unquote(path[len("/api/preview/"):]))
            picture = app.previews.get(livery["catalogId"]) if livery and livery.get("catalogId") else None
            if picture:
                self.send_file(picture, cache=True)
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        # Read the body before any answer: closing the connection with an unread body resets it on Windows.
        body = self.read_body()
        if not self.from_this_computer():
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self.send_json({"error": "Expected application/json"}, 415)
            return
        path = urllib.parse.urlparse(self.path).path
        app = self.app
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except ValueError as err:
            self.send_json({"error": "Invalid JSON: %s" % err}, 400)
            return
        if path == "/api/parse-vmr":
            self.send_json({"rules": parse_vmr(data.get("text", ""))})
        elif path == "/api/build":
            self.send_json({"text": build_vmr(data.get("rules", []), data.get("comment"))})
        elif path == "/api/save":
            name = Path(data.get("fileName") or "custom.vmr").name
            if not name.lower().endswith(".vmr"):
                name += ".vmr"
            target = app.output_dir / name
            try:
                app.output_dir.mkdir(parents=True, exist_ok=True)
                target.write_text(build_vmr(data.get("rules", []), data.get("comment")), encoding="utf-8", newline="")
            except OSError as err:
                self.send_json({"error": "Could not write %s: %s" % (target, err)}, 500)
                return
            app.saved(target)
            self.send_json({"path": str(target.resolve()), "outputDir": str(app.output_dir)})
        elif path == "/api/settings":
            # the page sends the settings it changed (file name, ticked presets, MTL choice)
            self.send_json({"settings": app.settings.update(data.get("settings") or {})})
        else:
            self.send_error(404)


class JsApi:
    """Functions the page can call through window.pywebview.api when the GUI runs in its own window."""

    def __init__(self, app=None):
        # Underscore: pywebview exposes every public attribute of this object to the page and walks
        # it recursively. Walking the Window object (and the .NET form behind it) never finishes and
        # the page then never gets its window.pywebview.api.
        self._window = None
        self._app = app

    def save_as(self, file_name, text):
        """Shows the Windows "Save as" dialog, opened in the folder of the last saved VMR, and writes the VMR
        text to the chosen file."""
        import webview
        folder = str(self._app.output_dir.resolve()) if self._app else ""
        result = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=folder, save_filename=file_name, file_types=("VMR files (*.vmr)", "All files (*.*)"))
        if not result:
            return {"cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            Path(path).write_text(text, encoding="utf-8", newline="")
        except OSError as err:
            return {"error": str(err)}
        if self._app:
            self._app.saved(path)
            return {"path": str(path), "outputDir": str(self._app.output_dir)}
        return {"path": str(path)}

    def open_file(self):
        """Shows the "Open" dialog and returns the text of the chosen VMR file."""
        import webview
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("VMR files (*.vmr)", "All files (*.*)"))
        if not result:
            return {"cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            return {"name": Path(path).name, "text": _read_text(path)}
        except OSError as err:
            return {"error": str(err)}


def show_window(url, server, app=None):
    """Shows the GUI in its own window. Returns False when pywebview is not available."""
    try:
        import webview
    except ImportError as err:
        print("pywebview is not installed (%s), opening the browser instead." % err)
        return False
    api = JsApi(app)
    print("  Opening the window (pywebview %s)." % getattr(webview, "__version__", "?"))
    window = webview.create_window("IVAO VMR generator", url, js_api=api, width=1500, height=950, min_size=(1000, 650))
    api._window = window
    loaded = threading.Event()

    def on_loaded():
        print("  Page loaded in the window.")
        loaded.set()
    window.events.loaded += on_loaded
    # Used by the build workflow to check that the window really opens: close it again once the page
    # has loaded (closing a window whose page is still loading can hang WebView2).
    if SELF_TEST:
        def close_soon():
            import time
            if not loaded.wait(30):
                print("  Self-test: the page did not load within 30 s.")
            time.sleep(2)
            print("  Self-test: closing the window.")
            window.destroy()
        webview.start(close_soon)
        if not loaded.is_set():
            raise RuntimeError("Self-test: the page never loaded in the window.")
    else:
        webview.start()
    print("  Window closed.")
    server.shutdown()
    return True


def main():
    parser = argparse.ArgumentParser(description="GUI for building a custom vPilot VMR on top of the IVAO MTL.")
    parser.add_argument("-d", "--directory", default=DEFAULT_DIR, help="folder that contains SimObjects/Airplanes (default: %s)" % ("the folder of the .exe" if FROZEN else "current folder"))
    parser.add_argument("-p", "--output-directory", default=None, help="folder where VMR files are saved (default: the folder of the last saved VMR, the first time the same folder as -d)")
    parser.add_argument("--port", type=int, default=8765, help="port of the local server (default: 8765, a free port is used if it is taken)")
    parser.add_argument("--browser", action="store_true", help="show the GUI in the web browser instead of its own window")
    parser.add_argument("--no-browser", action="store_true", help="only run the server, do not open a window or a browser")
    args = parser.parse_args()

    print("IVAO VMR generator GUI " + APP_VERSION)
    settings = Settings(SETTINGS_FILE).load()
    app = Handler.app = App(args.directory, args.output_directory, settings)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        # The port is taken (for example by a second copy of the GUI): let the system pick a free one.
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = "http://127.0.0.1:%d/" % server.server_address[1]
    print("  Settings: " + str(SETTINGS_FILE))
    print("  Models folder: " + os.path.abspath(args.directory))
    print("  Output folder: " + os.path.abspath(app.output_dir))
    print("  GUI address: " + url)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        if args.no_browser:
            print("  Server only (--no-browser). Press Ctrl+C to stop.")
            server_thread.join()
        elif not args.browser and show_window(url, server, app):
            pass
        else:
            if SELF_TEST:
                raise RuntimeError("The GUI window could not be opened (pywebview missing).")
            print("  Open " + url + " in your browser. Press Ctrl+C to stop.")
            webbrowser.open(url)
            server_thread.join()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.shutdown()


def report_crash(text):
    """Shows the error when there is no console to print it to (the .exe has none)."""
    print(text)
    if sys.platform == "win32" and not SELF_TEST:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text + "\n\nThe full log is in " + str(LOG_FILE), "IVAO VMR generator", 0x10)
        except Exception:
            pass


if __name__ == "__main__":
    if FROZEN:
        # The .exe has no console window: keep what the program prints in a log file next to it.
        try:
            sys.stdout = sys.stderr = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        except OSError:
            pass
    if SELF_TEST:
        # Backstop for the build workflow: never hang around, whatever the window does.
        def watchdog():
            import time
            time.sleep(40)
            print("  Self-test: watchdog fired, the program did not finish in time.")
            sys.stdout.flush()
            os._exit(3)
        threading.Thread(target=watchdog, daemon=True).start()
    exit_code = 0
    try:
        main()
    except Exception:
        import traceback
        report_crash(traceback.format_exc())
        exit_code = 1
    # The window toolkit (pywebview, .NET) can leave threads behind that would keep the process alive
    # after the window is closed; end the process explicitly.
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(exit_code)
