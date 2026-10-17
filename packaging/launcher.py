"""Frozen-application entry point (PyInstaller)."""

import sys

from docueditor.app import main

if __name__ == "__main__":
    raise SystemExit(main())
