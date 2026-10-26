# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the portable GUI: one self-contained executable, no installation needed.
#
#   pip install pyinstaller
#   pyinstaller build_exe.spec
#
# The result is dist/IVAO_VMR_Generator.exe (on Windows). The gui and presets folders are bundled
# inside the file; vmr_gui.py unpacks them at start. GitHub Actions builds it on every push
# (.github/workflows/build-exe.yml), signs it through SignPath Foundation and attaches it to the
# release when a tag is pushed.
#
# APP_VERSION (environment variable, e.g. 1.2.0) is written into the Windows version resource of the
# exe as product and file version. The workflow sets it from the tag; a local build gets 0.0.0.
# The product name and version are part of the SignPath Foundation requirements: every release has to
# carry the project name and a consistent version in its file metadata.

import os
import sys

APP_NAME = "IVAO_VMR_Generator"
PRODUCT_NAME = "create-ivao-vmr"
APP_VERSION = os.environ.get("APP_VERSION", "0.0.0").lstrip("v")


def version_tuple(version):
    parts = []
    for piece in version.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    parts = (parts + [0, 0, 0, 0])[:4]
    return tuple(parts)


def write_version_file(path):
    numbers = version_tuple(APP_VERSION)
    text = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=%(numbers)s,
    prodvers=%(numbers)s,
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'create-ivao-vmr contributors'),
         StringStruct('FileDescription', 'IVAO VMR generator: build custom vPilot model matching rules for the IVAO MTL'),
         StringStruct('FileVersion', '%(version)s'),
         StringStruct('InternalName', '%(app)s'),
         StringStruct('LegalCopyright', 'Apache License 2.0, https://github.com/vojta48/create-ivao-vmr'),
         StringStruct('OriginalFilename', '%(app)s.exe'),
         StringStruct('ProductName', '%(product)s'),
         StringStruct('ProductVersion', '%(version)s')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""" % {"numbers": numbers, "version": APP_VERSION, "app": APP_NAME, "product": PRODUCT_NAME}
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


block_cipher = None

a = Analysis(
    ["vmr_gui.py"],
    pathex=[],
    binaries=[],
    datas=[("gui", "gui"), ("presets", "presets")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "doctest", "test"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Keep the console window: it shows the address of the GUI and any error.
    console=True,
    disable_windowed_traceback=False,
    # The version resource exists on Windows only; PyInstaller ignores it elsewhere.
    version=write_version_file(os.path.join(workpath, "version_info.txt")) if sys.platform == "win32" else None,
)
