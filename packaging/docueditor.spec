# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec shared by the Linux, Windows and macOS build jobs.

Environment:
  DOCUEDITOR_NAME      output name (default: docueditor)
  DOCUEDITOR_ONEFILE   "1" for a single-file executable, "0" for a directory
"""

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - provided by PyInstaller
NAME = os.environ.get("DOCUEDITOR_NAME", "docueditor")
ONEFILE = os.environ.get("DOCUEDITOR_ONEFILE", "0") == "1"

if sys.platform == "win32":
    ICON = ROOT / "packaging" / "icons" / "docueditor.ico"
elif sys.platform == "darwin":
    ICON = ROOT / "packaging" / "icons" / "docueditor.icns"
else:
    ICON = None
ICON_PATH = str(ICON) if ICON is not None and ICON.exists() else None

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(ROOT / "src" / "docueditor" / "resources" / "style.qss"), "docueditor/resources"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
)

pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        icon=ICON_PATH,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        icon=ICON_PATH,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name=NAME,
    )
    if sys.platform == "darwin":
        app = BUNDLE(
            coll,
            name=f"{NAME}.app",
            icon=ICON_PATH,
            bundle_identifier="io.github.avis-illusio.docueditor",
            info_plist={
                "NSHighResolutionCapable": True,
                "CFBundleDisplayName": "Docueditor",
                "NSHumanReadableCopyright": "GPL-3.0-only",
            },
        )
