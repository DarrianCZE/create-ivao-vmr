# AGENTS.md

Guidance for AI coding agents (and humans) working on this repository.

> **The test suite is part of every change.** Any change to behaviour (a new feature, a bug fix, a new
> endpoint, a new GUI function, a new MTL quirk, a new bundled dependency) comes with new or updated tests
> in `tests/` **in the same commit**. A change without tests is not finished. Run the whole suite before
> you say you're done: `python -m unittest discover -s tests`. See [The test suite](#the-test-suite).

## What this project is

`create-ivao-vmr` generates **vPilot model-matching rule files (`.vmr`)** for the
**IVAO MTL** (Multiplayer Traffic Library) installed in **Microsoft Flight Simulator 2020 or 2024**.
VATSIM pilots use vPilot. vPilot shows other pilots' aircraft in the sim using installed models, and
the VMR tells it which MTL livery to load for a given callsign and aircraft type.

- Upstream repository: **https://github.com/vojta48/create-ivao-vmr**. Pull requests go there.
  Forks (for example `DarrianCZE/create-ivao-vmr`) push branches and open PRs against `vojta48:main`.
- Originally written by andrewward2001. The AIG (Alpha India Group) mode is inherited from that version
  and still supported, but the IVAO MTL is the focus.
- vPilot docs: https://vpilot.rosscarlson.dev/Documentation · MTL: https://mtl.ivao.aero/
  (mtl.ivao.aero returns 403 to automated fetches; use an installed MTL as the reference instead).

## Repository layout

| Path | What it is |
| --- | --- |
| `create_vmr.py` | The command-line script. **Standalone, standard library only.** Users drop this single file into `Packages/Community/IVAO_MTL` and run it, so it must never import anything from this repo. It also holds the shared rule logic that the GUI imports. |
| `vmr_gui.py` | GUI backend: a local `ThreadingHTTPServer` (127.0.0.1) plus a pywebview window, or the browser when pywebview isn't installed. It imports its rule logic from `create_vmr.py`. |
| `gui/` | Static front end (`index.html`, `app.js`, `style.css`). Plain JS, no build step, no frameworks, no CDN. |
| `presets/` | Ready-made `.vmr` rule sets offered in the GUI. A `<!-- comment -->` in the file becomes its description. |
| `tests/` | The `unittest` suite (see [The test suite](#the-test-suite)). It builds a fake MTL in temp folders, so it needs no installed MTL. |
| `LICENSE`, `NOTICE` | Apache 2.0 (the unmodified text) and the copyright and attribution notice. |
| `tools/collect_licenses.py`, `tools/licenses/` | Generate `THIRD-PARTY-LICENSES.txt` for the release from the packages bundled into the exe. |
| `build_exe.spec` | PyInstaller spec for the portable `IVAO_VMR_Generator.exe` (bundles `gui/` and `presets/`). |
| `.github/workflows/build-exe.yml` | CI: tests, then exe build, server and window smoke tests, SignPath signing and release on `v*` tags. |

## Domain knowledge you need

### How vPilot matches (this drives every design decision)
- A rule is `<ModelMatchRule CallsignPrefix="DLH" TypeCode="A320" ModelName="A320DLH//A320DLH2" />`.
  `ModelName` must equal a `title=` in an installed `aircraft.cfg`. If it lists several names separated
  by `//`, vPilot picks one **at random**.
- `CallsignPrefix` is a **starts-with** match on the callsign. A prefix that no callsign can start with
  (`@UN`, `ZZZ`, digits) never matches. A 2-letter prefix matches far too much (`RN` also catches `RNA123`).
  The only valid prefixes are 3-letter ICAO airline codes, or no prefix at all.
- Other attributes: `Callsign` (exact match) and `FlightNumberRange` (`"4439-4858"`).
- No `CallsignPrefix` makes it a **type-only rule**, which is the fallback for any airline of that type.
- vPilot makes **four passes**: prefix + exact type → prefix + *similar* type → type-only + exact type →
  type-only + similar type. Within a pass, the **first matching line wins**, so a later rule with the
  same conditions is never used. The order of the files only breaks ties within a pass.
- The order inside a generated VMR is therefore presets → user's own rules → MTL-generated rules.

### What the IVAO MTL looks like on disk
`Packages/Community/IVAO_MTL/`
- `SimObjects/Airplanes/IVAO_<model>/aircraft.cfg`: one `[fltsim.N]` section per livery, with:
  - `title="A320AAF"`: the MTL id, which is what goes into `ModelName`.
  - `texture="AAF"`: the texture folder suffix. It **contains typos** (`DAL` for Air Dolomiti, `EZE` for EasyJet), and its first three letters are only a fallback for the airline code.
  - `ui_type="A320"`: the ICAO type (first 4 characters).
  - `ui_variation="Aigle Azur (old) (AAF)"`: the catalog name. The **last `(XXX)` is the ICAO airline code**, and the groups before it describe special liveries.
- `SimObjects/Airplanes/IVAO_<model>/ivao.cfg`: its `icao_type_designator` is **unreliable** (`GLID` for an A330, `B190` for an F100). Do not use it.
- `texture.<X>/ivao.ini`: `mtl_version = 11636` is the catalog number of the livery, used for the preview picture.
- `texture.<X>/ivao.liv`: a copy of that livery's `[fltsim]` block.
- `mtl.dat`: one line per livery, `id,catalog name,0.0,0.0,catalogNumber`. The name can contain commas, so take the last field.
- `Doc8643.txt` (ICAO type table), `related.txt` (similar types), `layout.json`, `manifest.json`: MSFS/MTL files that this project doesn't use.
- Known MTL defects the code tolerates:
  - a `VERSION]` header missing its `[`: `create_vmr.py` repairs it **in the file**, while the GUI repairs it **in memory only**;
  - duplicated sections (hence `strict=False`);
  - files that are UTF-8 with a BOM, or cp1252.
- Special airline codes:
  - `default` texture or no texture: the plain model, which becomes a **type-only** rule.
  - Texture equal to the type (`HAR` for "AV-8 Harrier") with no catalog code: the plain model, **type-only**.
  - Type `ZZZZ` (blimp, balloon): **type-only**. The invisible dummy (texture `dummy`, "No Model (Invisible)")
    is **left out**, so vPilot never picks it at random.
  - A name with the airline code in an earlier bracket ("Emirates (UAE) (NBA)"): the earlier code that the
    texture starts with wins.
  - `ZZZ` (no airline) and `@xx` (military/government): **left out** of the VMR, unless the catalog name gives a real code such as `(USN)`. The GUI still lists them (`inVmr: false`).

## Invariants: do not break these

1. **The script and the GUI generate identical rules.** The logic lives once, in `create_vmr.py`:
   `mtl_airline_code`, `mtl_type_code`, `is_standard_livery`, `group_rules`, `xml_attr`.
   `vmr_gui.Library` must call these and must not reimplement them. `tests/test_parity.py` enforces this.
2. **`create_vmr.py` stays a single standalone file** that runs with any Python 3 standard library.
   The GUI may depend on `pywebview`. Nothing else may be added as a runtime dependency.
3. **`build_vmr` (Python) and `buildVmr` (`gui/app.js`) produce the same text.** "Save to output folder"
   uses the Python one, while the preview, "Save as" and the browser download use the JS one. Change both together.
4. **Importing a VMR must not make a rule broader.** Keep `Callsign` and `FlightNumberRange`
   (as `exactCallsign` / `flightNumbers`) through parse → GUI → build.
5. **The GUI never writes into the MTL.** It only writes VMR files to the output folder, previews to `previews/`, and `vmr_gui_settings.json` and `vmr_gui.log` next to the program.
6. **The local server answers only this computer.** It checks the Host header, POSTs must be `application/json`,
   and there is no endpoint that reads arbitrary paths. Keep it that way when you add endpoints.
7. **The README privacy policy must stay true.** It is part of the SignPath Foundation code-signing
   requirements. If the program starts contacting a new host or sending new data, update the policy in the same PR.
8. Output files: UTF-8. GUI VMRs use CRLF. Escape every attribute value with `xml_attr`.
9. **Licensing.** The project is Apache 2.0 and derived from Andrew Ward's original, so the license cannot be
   changed. Don't edit the `LICENSE` text; copyright holders and attribution go in `NOTICE`. When the exe gets
   a new bundled dependency, add it to `PACKAGES` in `tools/collect_licenses.py`. The script fails the build
   when a license text is missing; put a copy into `tools/licenses/` if the wheel does not ship one.
10. **Settings stay compatible between versions.** `vmr_gui_settings.json` (next to the program) keeps the VMR
    name, the last save folder, the ticked presets and the MTL choice. The rules for changing it (see the
    "Settings" section in `vmr_gui.py`):
    - **Adding a setting:** add it to `SETTINGS` with a default and a check function. **Don't** raise
      `SETTINGS_VERSION`: old files simply get the default.
    - Never rename a key or change the meaning or type of an existing one in place. Add a new key instead
      and leave the old one unused.
    - Only a change old files really cannot follow raises `SETTINGS_VERSION`. Raise
      `OLDEST_SUPPORTED_SETTINGS_VERSION` only when old files must be thrown away. Those files are then deleted
      at start, and the GUI tells the user once that the settings were from a version that is no longer
      supported and were reset. Both changes need a test in `tests/test_settings.py`.
    - Settings must never stop the program: invalid values fall back to their default one by one, unknown
      keys (also inside groups such as `mtlRules`) are kept on write, and a failed write is only logged.
    - `createdBy` / `savedBy` are the app version from `version.txt` (written by `build_exe.spec`, `dev` from
      source). They are information only; compatibility is decided by `settingsVersion`.
    - Tests use `Settings(None)` (in memory) or a temp folder, never the real file next to the program.

## The test suite

**Keep it up to date with every change. This is not optional.** The tests are the only thing that stops the
script and the GUI from drifting apart again, and the only check before a signed release goes out. When you
change behaviour, update the tests in the same commit:

- **New behaviour → new tests.** Bug fixes get a test that fails without the fix.
- **Changed behaviour → change the tests deliberately.** Don't weaken or delete an assertion just to get the
  suite green. If an expectation really changed (for example how a livery's airline code is chosen), update
  it and explain why in the commit message.
- **New MTL quirk found in a real installation → add it to the fake MTL** (`LIVERIES` in `tests/support.py`,
  with a comment), so that `test_parity.py` and `test_script.py` cover it from then on.
- **New endpoint, GUI function, preset, option or bundled package → extend the matching test file** (table below).
- **Never skip or disable tests to make CI pass.** The only allowed skips are the existing ones: no Node.js,
  no pywebview, no `IVAO_MTL_DIR`.

Run it:
- Everything: `python -m unittest discover -s tests` (Windows: `py -3 -m unittest discover -s tests`). Standard
  library only; it takes a few seconds. CI runs it before every build, and a failing test blocks the exe.
- One file: `python -m unittest discover -s tests -p test_server.py -v`. Don't use `-m unittest tests.x`,
  because `tests/` must be on the import path for `support.py`.
- Against a real MTL (read-only; the script runs on a copy):
  `IVAO_MTL_DIR=<...\Community\IVAO_MTL> python -m unittest discover -s tests -p test_real_mtl.py -v`.
  Run this after any change to the rule logic.
- The JavaScript tests run `gui/app.js` functions in Node.js (`node` on PATH). Install Node locally so they don't skip.

| File | Covers |
| --- | --- |
| `support.py` | Shared helpers, not tests: the fake MTL (`LIVERIES`, `make_mtl`, `write_model`), `run_script` (runs `create_vmr.main()` with fresh globals), `read_rules`, `ServerTestCase` (a real server on a free port). |
| `test_rules.py` | The pure rule functions in `create_vmr.py`: `livery_name_parts`, `is_standard_livery` (every neutral qualifier), `mtl_airline_code`, `mtl_type_code`, `xml_attr`, `build_rule`, `group_rules`. |
| `test_script.py` | `create_vmr.py` as a program: `VERSION]` repair (bytes, BOM, CRLF, read-only files), reading aircraft.cfg (encodings, duplicates, broken files, skipped liveries, unquoted titles), output files and counts, every command line option, the AIG mode. |
| `test_parity.py` | Invariant 1: the script and the GUI produce identical rules and standard rules from the same MTL, leave out the same liveries, and handle its odd cases the same way. |
| `test_library.py` | `vmr_gui.Library`: livery fields, catalog numbers (`ivao.ini`, `mtl.dat`), reported problems, never changing the MTL. |
| `test_vmr_format.py` | `parse_vmr`/`build_vmr` (all attributes, regex fallback, escaping, round trip), `_read_text`, `list_presets`. |
| `test_previews.py` | Catalog pictures: download once, cache, failures remembered, parallel requests. The network is mocked; tests must never go online. |
| `test_server.py` | Every HTTP endpoint, saving files, path traversal, and invariant 6 (Host check, JSON-only POST, no file-reading endpoint). |
| `test_window.py` | The pywebview file dialogs (`JsApi`) and the fallback without pywebview, with a fake `webview` module. |
| `test_settings.py` | Invariant 10: the settings file round trip, files from older, newer, unsupported and broken versions, the notice, the output folder from the last save, `/api/settings`, the Save as dialog, the app version. |
| `test_frontend.py` | `index.html` ↔ `app.js` ↔ server consistency, and the JS functions (`buildVmr` identical to `build_vmr`, invariant 3) run in Node.js. |
| `test_project.py` | Presets are valid and have no shadowed rules, license files and headers, `collect_licenses.py`, build spec, workflow, `.gitignore`, `create_vmr.py` stays standard-library only. |
| `test_real_mtl.py` | Optional checks against a real installation (`IVAO_MTL_DIR`). Skipped otherwise. |

Writing tests: use `unittest` and the standard library only (no pytest, no new dependencies). Use temp folders
(`TempDirTestCase`) and never the real MTL or the repo folder for output. Mock the network and pywebview. Keep the
plain, explanatory comment style of the rest of the code.

## Working on the code

- Run the tests (see above) before and after every change.
- Check the JS syntax: `node --check gui/app.js` (also part of `test_frontend.py`).
- Run the GUI from source: `python vmr_gui.py -d <IVAO_MTL folder> -p <output folder> [--browser | --no-browser] [--port N]`.
- **Testing against a real MTL:** `create_vmr.py` rewrites broken `aircraft.cfg` files in place. Never point it
  at someone's live MTL while experimenting. Copy `SimObjects/Airplanes/*/aircraft.cfg` (plus `mtl.dat`) to a
  scratch folder and run on the copy. `vmr_gui.Library(...).scan()` is read-only and safe on a live install.
  A useful check after rule changes: compare `create_vmr` output with `Library.mtl_rules()` on the copy, and
  diff the rule set against the previous `ivaomtl.vmr` to see what changed for users.
- Build the exe (Windows): `pip install pyinstaller pywebview`, then `pyinstaller build_exe.spec`, which gives `dist/IVAO_VMR_Generator.exe`.
  Never commit `build/`, `dist/`, `previews/` or logs (see `.gitignore`).

## Style

- Match the existing code. The comments are full sentences in plain English that explain *why*, often with
  a concrete MTL example (`texture="DAL"` for Air Dolomiti). Keep the comment density of the surrounding code.
- Python: standard library, `%`-formatting and string concatenation as in the surrounding code, no type hints,
  module-level globals in `create_vmr.py` (CLI style). New pure helpers there are fine and preferred.
- JS: one IIFE in `app.js`, the `el()` helper to build the DOM, `state` object, `api()` for server calls.
- User-facing text (README, GUI labels, console output) is plain, friendly English for flight simmers,
  not developers. Explain vPilot consequences ("this rule is never used because…").
- The working tree uses CRLF via `core.autocrlf`, and git stores LF. Don't create mixed line endings.

## Git and releases

- Branch from `main`. Never commit directly to `main`. Open PRs against `vojta48/create-ivao-vmr:main`.
- CI must be green: the tests, the exe build, and both smoke tests (server and window).
- Every PR that changes behaviour includes the matching test changes. Reviewers should reject it otherwise.
- A release is a pushed `v*` tag. CI builds it, SignPath signs it with a manual approval, and it is attached to
  the GitHub release. `APP_VERSION` comes from the tag. Releases are never built on a developer machine.
