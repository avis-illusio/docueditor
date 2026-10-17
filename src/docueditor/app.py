"""Application entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from . import APP_NAME, __version__
from .main_window import MainWindow
from .project import DocusaurusProject, ProjectError


def resources_dir() -> Path:
    return Path(__file__).resolve().parent / "resources"


def load_stylesheet() -> str:
    path = resources_dir() / "style.qss"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv if argv is None else argv)
    if (
        os.environ.get("QT_QPA_PLATFORM") is None
        and not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
    ):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    if "--version" in arguments:
        print(f"{APP_NAME} {__version__}")
        return 0

    app = QApplication(arguments)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("avis-illusio")
    app.setDesktopFileName("docueditor")
    app.setStyleSheet(load_stylesheet())

    window = MainWindow()
    window.restore_window_state()
    window.show()
    if "--self-test" in arguments:
        app.processEvents()
        return 0

    project_args = [arg for arg in arguments[1:] if not arg.startswith("-")]
    if project_args:
        try:
            project = DocusaurusProject(project_args[0]).load()
        except (ProjectError, OSError):
            project = None
        if project is not None:
            window._load_project(project)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
