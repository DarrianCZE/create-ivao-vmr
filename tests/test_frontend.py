# The front end in gui/: the page and the script fit together, and the pure functions of app.js behave like
# their Python counterparts (AGENTS.md, invariant 3). The JavaScript tests need Node.js and are skipped
# without it (GitHub's Windows runners have it).

import json
import re
import shutil
import subprocess
import unittest

from support import ROOT, vmr_gui

GUI = ROOT / "gui"
APP_JS = (GUI / "app.js").read_text(encoding="utf-8")
INDEX = (GUI / "index.html").read_text(encoding="utf-8")
NODE = shutil.which("node")
# Created by app.js itself (datalists for the inputs)
DYNAMIC_IDS = {"airlines", "types", "models"}


def js_function(name):
    """The source of a top-level function of the app.js IIFE (indented by two spaces)."""
    match = re.search(r"^  function %s\(.*?^  }$" % name, APP_JS, re.S | re.M)
    if not match:
        raise AssertionError("function %s not found in app.js" % name)
    return match.group(0)


def run_js(functions, expression, data):
    """Evaluates expression with the given app.js functions defined and `data` bound; returns the JSON result."""
    script = "\n".join(js_function(f) for f in functions) + \
        "\nconst data = JSON.parse(require('fs').readFileSync(0, 'utf8'));\nprocess.stdout.write(JSON.stringify(%s));" % expression
    result = subprocess.run([NODE, "-e", script], input=json.dumps(data), capture_output=True, text=True, encoding="utf-8", timeout=60)
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class PageTest(unittest.TestCase):
    def test_every_element_the_script_uses_exists(self):
        ids = set(re.findall(r'\bid="([^"]+)"', INDEX))
        used = set(re.findall(r'\$\("([^"]+)"\)', APP_JS))
        self.assertEqual(used - ids - DYNAMIC_IDS, set())

    def test_static_files_exist(self):
        for path in re.findall(r'(?:src|href)="/static/([^"]+)"', INDEX):
            self.assertTrue((GUI / path).is_file(), path)

    def test_no_external_resources(self):
        # the GUI has to work offline and without a CDN
        self.assertNotRegex(INDEX, r'(?:src|href)="https?://(?!mtl\.ivao\.aero)')

    def test_api_paths_exist_on_the_server(self):
        server = (ROOT / "vmr_gui.py").read_text(encoding="utf-8")
        for path in set(re.findall(r'"(/api/[a-z\-./]+)', APP_JS)):
            self.assertIn('"%s' % path, server, path)


@unittest.skipUnless(NODE, "Node.js not installed")
class JavaScriptTest(unittest.TestCase):
    RULES = [
        {"callsign": "DLH", "exactCallsign": "DLH1", "flightNumbers": "1-9", "type": "A320", "models": ["A", "B&C", 'Q"<>']},
        {"callsign": "", "type": "C172", "models": ["C172"]},
        {"callsign": "AAA", "type": "", "models": ["X"]},
        {"callsign": "AAA", "type": "B738", "models": []},
    ]

    def test_syntax(self):
        result = subprocess.run([NODE, "--check", str(GUI / "app.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_build_vmr_is_the_same_as_python(self):
        for comment in ("Presets: a -- b; IVAO MTL: all liveries", ""):
            js = run_js(["buildVmr"], "buildVmr(data.rules, data.comment)", {"rules": self.RULES, "comment": comment})
            self.assertEqual(js, vmr_gui.build_vmr(self.RULES, comment or None))

    def test_normalise_rule(self):
        result = run_js(["normaliseRule"], "data.map(normaliseRule)", [
            {"callsign": " dlh ", "type": "a320 ", "models": [" A ", "", "B"]},
            {"exactCallsign": "okabc ", "flightNumbers": " 1-2 "},
        ])
        self.assertEqual(result, [
            {"callsign": "DLH", "type": "A320", "models": ["A", "B"]},
            {"callsign": "", "type": "", "models": [], "exactCallsign": "OKABC", "flightNumbers": "1-2"},
        ])

    def test_models_from_text(self):
        self.assertEqual(run_js(["modelsFromText"], "modelsFromText(data)", " A // B//// C "), ["A", "B", "C"])

    def test_rule_key_separates_conditions(self):
        keys = run_js(["ruleKey"], "data.map(ruleKey)", [
            {"callsign": "DLH", "type": "A320"},
            {"callsign": "DLH", "type": "A320", "exactCallsign": "DLH1"},
            {"callsign": "DLH", "type": "A320", "flightNumbers": "1-9"},
            {"callsign": "DLH", "type": "A321"},
            {"callsign": "DLH", "type": "A320"},
        ])
        self.assertEqual(len(set(keys)), 4)
        self.assertEqual(keys[0], keys[4])

    def test_rule_conditions(self):
        self.assertEqual(run_js(["ruleConditions"], "data.map(ruleConditions)", [
            {"callsign": "", "type": "C172"}, {"callsign": "DLH", "exactCallsign": "DLH1", "flightNumbers": "1-9", "type": "A320"}]),
            ["* C172", "DLH =DLH1 #1-9 A320"])

    def test_python_parse_and_js_build_round_trip(self):
        rules = vmr_gui.parse_vmr(vmr_gui.build_vmr(self.RULES[:2]))
        js = run_js(["buildVmr"], "buildVmr(data, '')", rules)
        self.assertEqual(vmr_gui.parse_vmr(js), rules)


if __name__ == "__main__":
    unittest.main()
