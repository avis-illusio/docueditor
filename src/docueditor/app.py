"""Application entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .input_method import configure
from .project import DocusaurusProject, ProjectError



def _system_libstdcpp() -> str | None:
    """Return a system libstdc++ that provides CXXABI_1.3.15, if available."""
    candidates = (
        "/usr/lib/libstdc++.so.6",
        "/usr/lib64/libstdc++.so.6",
        "/usr/lib/x86_64-linux-gnu/libstdc++.so.6",
        "/usr/lib/aarch64-linux-gnu/libstdc++.so.6",
    )
    for candidate in candidates:
        try:
            with open(candidate, "rb") as handle:
                if b"CXXABI_1.3.15" in handle.read():
                    return candidate
        except OSError:
            continue
    return None


def _ensure_system_libstdcpp() -> None:
    """Preload the system libstdc++ so system fcitx5/ibus plugins can load.

    PyInstaller bundles an older libstdc++ from the build image.  fcitx5-qt
    plugins built on a newer distribution need CXXABI_1.3.15, which the
    bundled copy does not provide.  Re-exec once with the system library
    preloaded when that is the case.
    """
    if not sys.platform.startswith("linux") or not getattr(sys, "frozen", False):
        return
    if os.environ.get("DOCUEDITOR_LIBSTDCPP_PRELOADED"):
        return
    if "libstdc++.so" in os.environ.get("LD_PRELOAD", ""):
        os.environ["DOCUEDITOR_LIBSTDCPP_PRELOADED"] = "1"
        return
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "libstdc++.so.6"
    if not bundled.exists():
        return
    system = _system_libstdcpp()
    if system is None:
        return
    os.environ["DOCUEDITOR_LIBSTDCPP_PRELOADED"] = "1"
    existing = os.environ.get("LD_PRELOAD", "")
    os.environ["LD_PRELOAD"] = system + (os.pathsep + existing if existing else "")
    os.execv(sys.executable, [sys.executable, *sys.argv[1:]])



def resources_dir() -> Path:
    return Path(__file__).resolve().parent / "resources"


def load_stylesheet() -> str:
    path = resources_dir() / "style.qss"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


HELP_TEXT = f"""{APP_NAME} {__version__}
Docusaurus 文档所见即所得编辑器

用法：
  docueditor [选项] [项目目录]

选项：
  -h, --help            显示本帮助并退出
  --version             显示版本并退出
  --im <auto|fcitx5|ibus|none>
                        设置输入法模块（Linux，重启生效）
  --im-status           打印输入法诊断信息
  --self-test           启动后立即退出（打包自检）

也可以直接打开项目：
  docueditor /path/to/docusaurus-site
"""


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv if argv is None else argv)

    if "--help" in arguments or "-h" in arguments:
        print(HELP_TEXT)
        return 0
    if "--version" in arguments:
        print(f"{APP_NAME} {__version__}")
        return 0

    if (
        os.environ.get("QT_QPA_PLATFORM") is None
        and not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
    ):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    _ensure_system_libstdcpp()

    # Must happen before QApplication: Qt reads QT_IM_MODULE and the plugin
    # path only once while constructing the platform integration.
    arguments, im_status = configure(arguments)

    if "--im-status" in arguments:
        from PySide6 import __version__ as pyside_version
        from PySide6.QtCore import qVersion

        print(f"Docueditor {__version__}")
        print(f"PySide6 {pyside_version} / Qt {qVersion()}")
        print(f"session: {os.environ.get('XDG_SESSION_TYPE', '?')}")
        print(f"platform: {os.environ.get('QT_QPA_PLATFORM', 'auto')}")
        print(im_status.report())
        return 0

    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

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
