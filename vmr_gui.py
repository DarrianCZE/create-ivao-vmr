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
#   - add the rules generated from your MTL (the same rules create_vmr.py makes, all liveries or the
#     standard liveries only) after your own rules, so that one VMR file is enough in vPilot,
#   - save the result as a VMR file.
# Every livery links to its page in the MTL catalog (https://mtl.ivao.aero/catalog).
#
# Options:
#   -d | --directory [path]   folder that contains SimObjects/Airplanes (default: the current folder)
#   -p | --output-directory   folder where generated VMR files are saved (default: the current folder)
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
import urllib.parse
import webbrowser
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# The rule that decides whether a livery is the airline's standard livery or a special one is shared
# with create_vmr.py, so the GUI and the script produce the same standard-only VMR.
from create_vmr import is_standard_livery

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

# Page of a livery in the MTL catalog (https://mtl.ivao.aero/catalog). Pictures of the liveries are not
# shown: the thumbnails in the MTL are one generic picture for every livery, and the catalog pictures
# can only be found through the IVAO API, which needs an API key.
CATALOG_SEARCH = "https://mtl.ivao.aero/catalog?textureName={name}"


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
            name = _unquote(entry.get("ui_variation", ""))
            self.liveries[title] = {
                "id": title,
                "airline": texture[:3].upper() if len(texture) >= 3 else "",
                "type": ui_type[:4].upper(),
                "texture": texture,
                "name": name,
                "model": model_dir.name,
                "standard": is_standard_livery(texture, name),
            }

    def summary(self):
        return list(self.liveries.values())

    def mtl_rules(self, standard_only):
        """The rules create_vmr.py generates from the MTL: one rule per airline and aircraft type with all
        its liveries as alternatives. With standard_only the special liveries are left out, unless the
        airline has nothing but special liveries for that type (see create_vmr.py)."""
        groups = {}
        for livery in self.liveries.values():
            if not livery["type"] or "&" in livery["id"]:
                continue
            groups.setdefault((livery["airline"], livery["type"]), []).append(livery)
        rules = []
        for (airline, type_code), liveries in groups.items():
            if standard_only:
                standard = [l for l in liveries if l["standard"]]
                if standard:
                    liveries = standard
            rules.append({"callsign": airline, "type": type_code, "models": [l["id"] for l in liveries]})
        return rules

    def livery_list_csv(self):
        """The livery list create_vmr.py writes next to the VMR (<stem>_liveries.csv)."""
        kept = set()
        for rule in self.mtl_rules(True):
            kept.update(rule["models"])
        lines = ["mtlid;airline;type;texture;name;livery"]
        for livery in sorted(self.liveries.values(), key=lambda l: (l["airline"], l["type"], l["id"])):
            if livery["standard"]:
                kind = "standard"
            elif livery["id"] in kept:
                kind = "special (kept, no standard livery)"
            else:
                kind = "special"
            lines.append(";".join([livery["id"], livery["airline"], livery["type"], livery["texture"], livery["name"].replace(";", ","), kind]))
        return "\n".join(lines) + "\n"


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return value.strip()


# --------------------------------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------------------------------

class App:
    def __init__(self, models_root, output_dir):
        self.library = Library(models_root)
        self.output_dir = Path(output_dir)


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
                "mtlRules": {"all": app.library.mtl_rules(False), "standard": app.library.mtl_rules(True)},
                "catalogSearch": CATALOG_SEARCH,
            })
        elif path == "/api/rescan":
            app.library.scan()
            self.send_json({
                "liveries": app.library.summary(),
                "errors": app.library.errors,
                "mtlRules": {"all": app.library.mtl_rules(False), "standard": app.library.mtl_rules(True)},
            })
        elif path == "/api/livery-list.csv":
            body = app.library.livery_list_csv().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="ivaomtl_liveries.csv"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
            written = []
            try:
                app.output_dir.mkdir(parents=True, exist_ok=True)
                target.write_text(build_vmr(data.get("rules", []), data.get("comment")), encoding="utf-8", newline="")
                written.append(str(target.resolve()))
                if data.get("liveryList"):
                    # Like create_vmr.py: the list of liveries next to the VMR, with their catalog names.
                    csv_target = target.with_name(target.stem + "_liveries.csv")
                    csv_target.write_text(app.library.livery_list_csv(), encoding="utf-8", newline="")
                    written.append(str(csv_target.resolve()))
            except OSError as err:
                self.send_json({"error": "Could not write %s: %s" % (target, err)}, 500)
                return
            self.send_json({"path": written[0], "files": written})
        else:
            self.send_error(404)


class JsApi:
    """Functions the page can call through window.pywebview.api when the GUI runs in its own window."""

    def __init__(self):
        # Underscore: pywebview exposes every public attribute of this object to the page and walks
        # it recursively. Walking the Window object (and the .NET form behind it) never finishes and
        # the page then never gets its window.pywebview.api.
        self._window = None

    def save_as(self, file_name, text):
        """Shows the Windows "Save as" dialog and writes the VMR text to the chosen file."""
        import webview
        result = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=file_name, file_types=("VMR files (*.vmr)", "All files (*.*)"))
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
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("VMR files (*.vmr)", "All files (*.*)"))
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
