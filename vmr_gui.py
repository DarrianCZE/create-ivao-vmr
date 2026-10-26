#!/usr/bin/env python3
# Simple GUI for building a custom vPilot VMR file on top of the IVAO MTL.
#
# Run it from the IVAO MTL folder (Packages/Community/IVAO_MTL), the same place as create_vmr.py:
#   python vmr_gui.py
# It starts a small local web server (standard library only) and shows the GUI in its own window
# (through pywebview, "pip install pywebview"; without it the GUI opens in your browser instead).
# In the GUI you can:
#   - turn on ready-made rule sets from the "presets" folder (for example the Smartwings group),
#   - add your own ModelMatchRule lines (CallsignPrefix / TypeCode / ModelName, "//" for alternatives),
#   - see a preview of every livery (local thumbnail from the MTL, or the picture from the MTL catalog),
#   - save the result as a VMR file.
#
# Options:
#   -d | --directory [path]   folder that contains SimObjects/Airplanes (default: the current folder)
#   -p | --output-directory   folder where generated VMR files are saved (default: the current folder)
#   --port [number]           port of the local server (default: 8765)
#   --browser                 show the GUI in the web browser instead of its own window
#   --no-browser              only run the server, do not open a window or a browser

import argparse
import configparser
import csv
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

# When packed into an .exe with PyInstaller (see build_exe.spec), the gui and presets folders are bundled
# inside the executable and unpacked to a temporary folder (sys._MEIPASS). Files the user edits or that
# the GUI writes (own presets, the settings, the generated VMRs) live next to the .exe instead.
FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
GUI_DIR = BUNDLE_DIR / "gui"
PRESETS_DIRS = [BUNDLE_DIR / "presets", APP_DIR / "presets"]  # a preset next to the exe replaces a bundled one of the same name
SETTINGS_FILE = APP_DIR / "vmr_gui_settings.json"
LOG_FILE = APP_DIR / "vmr_gui.log"
# The script works in the folder it is run from, like create_vmr.py. The .exe works in its own folder,
# because Windows does not always start a double-clicked program in the folder it lies in.
DEFAULT_DIR = str(APP_DIR) if FROZEN else "."

# The MTL catalog (https://mtl.ivao.aero/catalog) shows the picture of a livery from this address.
# The numeric id of a texture comes from the IVAO API, which needs an API key (see settings in the GUI).
IVAO_API = "https://api.ivao.aero"
CATALOG_IMAGE = "https://download.ivao.aero/v2/aircraftsTextures/{id}/files/latest/image"
CATALOG_SEARCH = "https://mtl.ivao.aero/catalog?textureName={name}"
NOT_AVAILABLE_IMG = "https://static.ivao.aero/mtl/clouds.jpg"

THUMBNAIL_NAMES = ["thumbnail.jpg", "thumbnail.png", "thumbnail.JPG", "thumbnail_small.jpg"]


# --------------------------------------------------------------------------------------------------
# VMR reading and writing
# --------------------------------------------------------------------------------------------------

def parse_vmr(text):
    """Returns the ModelMatchRule entries of a VMR file as a list of dicts with
    callsign, type and models (list of ModelName alternatives)."""
    rules = []
    # Some hand-made VMR files are not well-formed XML (missing closing tag, comment after the root).
    # Try the XML parser first and fall back to a regular expression that only looks at the rules.
    try:
        root = ET.fromstring(text.strip())
        for rule in root.iter("ModelMatchRule"):
            rules.append(_make_rule(rule.get("CallsignPrefix", ""), rule.get("TypeCode", ""), rule.get("ModelName", "")))
        return rules
    except ET.ParseError:
        pass
    for match in re.finditer(r"<ModelMatchRule\b([^>]*)/?>", text):
        attrs = dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', match.group(1)))
        rules.append(_make_rule(attrs.get("CallsignPrefix", ""), attrs.get("TypeCode", ""), attrs.get("ModelName", "")))
    return rules


def _make_rule(callsign, type_code, model_name):
    return {
        "callsign": callsign.strip().upper(),
        "type": type_code.strip().upper(),
        "models": [m.strip() for m in model_name.split("//") if m.strip()],
    }


def build_vmr(rules, comment=None):
    """Builds the text of a VMR file from a list of rules (see parse_vmr for the format)."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<ModelMatchRuleSet>"]
    for rule in rules:
        if not rule.get("type") or not rule.get("models"):
            continue
        attrs = ""
        if rule.get("callsign"):
            attrs += ' CallsignPrefix="%s"' % _xml_attr(rule["callsign"])
        attrs += ' TypeCode="%s" ModelName="%s"' % (_xml_attr(rule["type"]), _xml_attr("//".join(rule["models"])))
        lines.append("<ModelMatchRule%s />" % attrs)
    lines.append("</ModelMatchRuleSet>")
    if comment:
        lines.append("<!-- %s -->" % comment.replace("--", "- -"))
    lines.append("<!-- VMR created by create-ivao-vmr GUI https://github.com/vojta48/create-ivao-vmr -->")
    return "\r\n".join(lines) + "\r\n"


def _xml_attr(value):
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


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
        if self.airplanes.is_dir():
            for model_dir in sorted(self.airplanes.iterdir()):
                cfg = model_dir / "aircraft.cfg"
                if cfg.is_file():
                    self._read_cfg(model_dir, cfg)
        self.scanned = True
        return self

    def _read_cfg(self, model_dir, cfg):
        config = configparser.ConfigParser(strict=False, interpolation=None)
        try:
            try:
                config.read(cfg, encoding="utf-8-sig")
            except UnicodeDecodeError:
                config = configparser.ConfigParser(strict=False, interpolation=None)
                config.read(cfg, encoding="cp1252")
        except (configparser.Error, UnicodeDecodeError) as err:
            self.errors.append("%s: %s" % (cfg, err))
        for section in config.sections():
            if not section.lower().startswith("fltsim"):
                continue
            entry = config[section]
            title = _unquote(entry.get("title", ""))
            if not title:
                continue
            texture = _unquote(entry.get("texture", ""))
            ui_type = _unquote(entry.get("ui_type", ""))
            self.liveries[title] = {
                "id": title,
                "airline": texture[:3].upper() if len(texture) >= 3 else "",
                "type": ui_type[:4].upper(),
                "texture": texture,
                "name": _unquote(entry.get("ui_variation", "")),
                "model": model_dir.name,
                "thumbnail": self._find_thumbnail(model_dir, texture),
            }

    @staticmethod
    def _find_thumbnail(model_dir, texture):
        folders = [model_dir / ("texture." + texture), model_dir / "texture"] if texture else [model_dir / "texture"]
        for folder in folders:
            for name in THUMBNAIL_NAMES:
                candidate = folder / name
                if candidate.is_file():
                    return str(candidate)
        return None

    def summary(self):
        return [
            {k: v for k, v in livery.items() if k != "thumbnail"} | {"hasThumbnail": livery["thumbnail"] is not None}
            for livery in self.liveries.values()
        ]


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return value.strip()


# --------------------------------------------------------------------------------------------------
# MTL catalog (optional, needs an IVAO API key)
# --------------------------------------------------------------------------------------------------

class Catalog:
    """Looks up the numeric id of a livery in the IVAO API so that the picture from the MTL catalog can be shown."""

    def __init__(self):
        self.cache = {}
        self.lock = threading.Lock()

    def image_url(self, texture_name, api_key):
        if not api_key:
            return None
        with self.lock:
            if texture_name in self.cache:
                return self.cache[texture_name]
        query = urllib.parse.urlencode({"page": 1, "perPage": 5, "isActive": "true", "textureName": texture_name})
        request = urllib.request.Request(IVAO_API + "/v2/aircraftsTextures?" + query, headers={"apiKey": api_key})
        url = None
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
            for item in data.get("items", []):
                if str(item.get("name", "")).upper() == texture_name.upper():
                    url = CATALOG_IMAGE.format(id=item["id"])
                    break
            if url is None and data.get("items"):
                url = CATALOG_IMAGE.format(id=data["items"][0]["id"])
        except (urllib.error.URLError, ValueError, KeyError) as err:
            print("Catalog lookup failed for %s: %s" % (texture_name, err))
            return None
        with self.lock:
            self.cache[texture_name] = url
        return url


# --------------------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------------------

def load_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------------------------------

class App:
    def __init__(self, models_root, output_dir):
        self.library = Library(models_root)
        self.output_dir = Path(output_dir)
        self.catalog = Catalog()
        self.settings = load_settings()


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

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # ----- routing -----
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path = url.path
        query = urllib.parse.parse_qs(url.query)
        app = self.app
        if path in ("/", "/index.html"):
            self.send_file(GUI_DIR / "index.html")
        elif path.startswith("/static/"):
            name = Path(path[len("/static/"):]).name
            self.send_file(GUI_DIR / name)
        elif path == "/api/state":
            if not app.library.scanned:
                app.library.scan()
            self.send_json({
                "modelsRoot": str(app.library.models_root),
                "airplanesFolder": str(app.library.airplanes),
                "libraryFound": app.library.airplanes.is_dir(),
                "outputDir": str(app.output_dir),
                "liveries": app.library.summary(),
                "errors": app.library.errors,
                "presets": list_presets(),
                "settings": {"hasApiKey": bool(app.settings.get("apiKey"))},
                "catalogSearch": CATALOG_SEARCH,
                "notAvailableImage": NOT_AVAILABLE_IMG,
            })
        elif path == "/api/rescan":
            app.library.scan()
            self.send_json({"liveries": app.library.summary(), "errors": app.library.errors})
        elif path.startswith("/api/thumbnail/"):
            mtl_id = urllib.parse.unquote(path[len("/api/thumbnail/"):])
            livery = app.library.liveries.get(mtl_id)
            if livery and livery["thumbnail"]:
                self.send_file(livery["thumbnail"], cache=True)
            else:
                self.send_error(404)
        elif path.startswith("/api/catalog-image/"):
            mtl_id = urllib.parse.unquote(path[len("/api/catalog-image/"):])
            image = app.catalog.image_url(mtl_id, app.settings.get("apiKey"))
            if image:
                self.send_response(302)
                self.send_header("Location", image)
                self.send_header("Cache-Control", "max-age=3600")
                self.end_headers()
            else:
                self.send_error(404)
        elif path == "/api/parse-vmr":
            # ?file=<path> reads a VMR file from disk (for example an existing custom VMR)
            file_path = query.get("file", [""])[0]
            if not file_path or not Path(file_path).is_file():
                self.send_json({"error": "File not found: " + file_path}, 404)
            else:
                self.send_json({"rules": parse_vmr(_read_text(file_path))})
        else:
            self.send_error(404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        app = self.app
        try:
            data = self.read_json()
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
            self.send_json({"path": str(target.resolve())})
        elif path == "/api/settings":
            if "apiKey" in data:
                app.settings["apiKey"] = data["apiKey"].strip()
                app.catalog.cache.clear()
            try:
                save_settings(app.settings)
            except OSError as err:
                self.send_json({"error": "Could not save settings: %s" % err}, 500)
                return
            self.send_json({"hasApiKey": bool(app.settings.get("apiKey"))})
        else:
            self.send_error(404)


class JsApi:
    """Functions the page can call through window.pywebview.api when the GUI runs in its own window."""

    def __init__(self):
        self.window = None

    def save_as(self, file_name, text):
        """Shows the Windows "Save as" dialog and writes the VMR text to the chosen file."""
        import webview
        result = self.window.create_file_dialog(webview.FileDialog.SAVE, save_filename=file_name, file_types=("VMR files (*.vmr)", "All files (*.*)"))
        if not result:
            return {"cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            Path(path).write_text(text, encoding="utf-8", newline="")
        except OSError as err:
            return {"error": str(err)}
        return {"path": str(path)}

    def open_file(self):
        """Shows the "Open" dialog and returns the text of the chosen VMR file."""
        import webview
        result = self.window.create_file_dialog(webview.FileDialog.OPEN, file_types=("VMR files (*.vmr)", "All files (*.*)"))
        if not result:
            return {"cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            return {"name": Path(path).name, "text": _read_text(path)}
        except OSError as err:
            return {"error": str(err)}


def show_window(url, server):
    """Shows the GUI in its own window. Returns False when pywebview is not available."""
    try:
        import webview
    except ImportError as err:
        print("pywebview is not installed (%s), opening the browser instead." % err)
        return False
    api = JsApi()
    window = webview.create_window("IVAO VMR generator", url, js_api=api, width=1500, height=950, min_size=(1000, 650))
    api.window = window
    # Used by the build workflow to check that the window really opens: close it again after a moment.
    self_test = os.environ.get("IVAO_VMR_GUI_SELFTEST") == "1"
    if self_test:
        def close_soon():
            import time
            time.sleep(5)
            window.destroy()
        webview.start(close_soon)
    else:
        webview.start()
    server.shutdown()
    return True


def main():
    parser = argparse.ArgumentParser(description="GUI for building a custom vPilot VMR on top of the IVAO MTL.")
    parser.add_argument("-d", "--directory", default=DEFAULT_DIR, help="folder that contains SimObjects/Airplanes (default: %s)" % ("the folder of the .exe" if FROZEN else "current folder"))
    parser.add_argument("-p", "--output-directory", default=DEFAULT_DIR, help="folder where VMR files are saved (default: the same folder)")
    parser.add_argument("--port", type=int, default=8765, help="port of the local server (default: 8765, a free port is used if it is taken)")
    parser.add_argument("--browser", action="store_true", help="show the GUI in the web browser instead of its own window")
    parser.add_argument("--no-browser", action="store_true", help="only run the server, do not open a window or a browser")
    args = parser.parse_args()

    Handler.app = App(args.directory, args.output_directory)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        # The port is taken (for example by a second copy of the GUI): let the system pick a free one.
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = "http://127.0.0.1:%d/" % server.server_address[1]
    print("IVAO VMR generator GUI")
    print("  Models folder: " + os.path.abspath(args.directory))
    print("  Output folder: " + os.path.abspath(args.output_directory))
    print("  GUI address: " + url)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        if args.no_browser:
            print("  Server only (--no-browser). Press Ctrl+C to stop.")
            server_thread.join()
        elif not args.browser and show_window(url, server):
            pass
        else:
            if os.environ.get("IVAO_VMR_GUI_SELFTEST") == "1":
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
    if sys.platform == "win32":
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
    try:
        main()
    except Exception:
        import traceback
        report_crash(traceback.format_exc())
        sys.exit(1)
