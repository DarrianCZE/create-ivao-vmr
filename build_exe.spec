# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the portable GUI: one self-contained executable, no installation needed.
#
#   pip install pyinstaller
#   pyinstaller build_exe.spec
#
# The result is dist/IVAO_VMR_Generator.exe (on Windows). The gui and presets folders are bundled
# inside the file; vmr_gui.py unpacks them at start. GitHub Actions builds it on every push
# (.github/workflows/build-exe.yml) and attaches it to the release when a tag is pushed.

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
    name="IVAO_VMR_Generator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Keep the console window: it shows the address of the GUI and any error.
    console=True,
    disable_windowed_traceback=False,
)
