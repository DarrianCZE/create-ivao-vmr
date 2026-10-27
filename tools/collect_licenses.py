#!/usr/bin/env python3
# Writes THIRD-PARTY-LICENSES.txt: the copyright notices and license texts of the third-party software
# that PyInstaller packs into IVAO_VMR_Generator.exe. The licenses (BSD, MIT, PSF) require them to come
# with every copy of the exe; the build workflow runs this after the build and attaches the file to the
# release next to LICENSE and NOTICE.
#
# Run it in the same Python environment that built the exe (standard library only):
#   python tools/collect_licenses.py dist/THIRD-PARTY-LICENSES.txt
# The texts are read from the installed packages, so the file always matches what was bundled.

import sys
from importlib import metadata
from pathlib import Path

# The packages that end up inside the exe: pywebview and what it needs on Windows, and PyInstaller
# (its bootloader starts the exe). Build-only tools (setuptools, pefile, ...) are not bundled.
PACKAGES = ["pywebview", "bottle", "proxy_tools", "typing_extensions", "pythonnet", "clr_loader", "cffi", "pycparser", "pyinstaller"]
LICENSE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")
# Copies of license texts that the installed packages do not contain, taken from the projects' repositories:
# the proxy_tools wheel has no license file, and the pywebview wheel bundles the WebView2 DLLs without
# Microsoft's license (it is only in the pywebview repository, webview/lib/).
FALLBACK_DIR = Path(__file__).resolve().parent / "licenses"


def license_files(dist):
    """The license files a package installed into its .dist-info folder."""
    files = []
    for file in dist.files or []:
        if ".dist-info" in str(file) and file.name.upper().startswith(LICENSE_NAMES):
            files.append(Path(dist.locate_file(file)))
    return files


def section(title, text):
    return "=" * 78 + "\n" + title + "\n" + "=" * 78 + "\n\n" + text.strip() + "\n\n"


def main(target):
    out = [
        "Third-party software in IVAO_VMR_Generator.exe\n"
        "(create-ivao-vmr itself is licensed under the Apache License 2.0, see LICENSE and NOTICE.)\n\n"
    ]
    missing = []

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        out.append(section("Python %d.%d.%d (PSF-2.0)" % sys.version_info[:3], python_license.read_text(encoding="utf-8", errors="replace")))
    else:
        missing.append("Python (%s)" % python_license)

    for name in PACKAGES:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
            continue
        # License-Expression is the modern field; older packages put the name (or the whole text) into License.
        kind = dist.metadata.get("License-Expression") or ((dist.metadata.get("License") or "").strip().splitlines() or ["see below"])[0]
        files = license_files(dist) or list(FALLBACK_DIR.glob(name + ".LICENSE*"))
        texts = [p.read_text(encoding="utf-8", errors="replace") for p in files]
        if not texts:
            missing.append(name)
            continue
        out.append(section("%s %s (%s)" % (dist.metadata["Name"], dist.version, kind), "\n\n".join(texts)))

    # pywebview ships the Microsoft WebView2 SDK (Microsoft.Web.WebView2.*.dll) with its own license.
    name = "Microsoft.Web.WebView2.LICENSE.md"
    try:
        import webview
        candidates = [Path(webview.__file__).parent / "lib" / name, FALLBACK_DIR / name]
    except ImportError:
        candidates = []
    webview2 = next((p for p in candidates if p.is_file()), None)
    if webview2:
        out.append(section("Microsoft WebView2 SDK (bundled with pywebview)", webview2.read_text(encoding="utf-8", errors="replace")))
    else:
        missing.append("Microsoft WebView2 SDK license")

    if missing:
        # A license that cannot be found must not silently disappear from a release.
        print("License texts not found: " + ", ".join(missing))
        return 1
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(target).write_text("".join(out), encoding="utf-8")
    print("Wrote " + str(target))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "THIRD-PARTY-LICENSES.txt"))
