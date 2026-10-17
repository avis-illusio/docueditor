"""Linux input-method integration (fcitx5 / ibus).

Qt only loads an input-context plugin when ``QT_IM_MODULE`` names one, and the
PySide6 wheel ships only the compose/ibus plugins.  fcitx5-qt installs its Qt6
plugin into the system plugin directory, so we build a tiny plugin overlay
containing symlinks to the system fcitx5/ibus plugins and prepend it to
``QT_PLUGIN_PATH`` before ``QApplication`` is created.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

CHOICES = ("auto", "fcitx5", "ibus", "none")
MODULE_FOR_CHOICE = {"fcitx5": "fcitx", "ibus": "ibus"}

DEFAULT_PLUGIN_DIRS = (
    Path("/usr/lib/qt6/plugins"),
    Path("/usr/lib64/qt6/plugins"),
    Path("/usr/lib/x86_64-linux-gnu/qt6/plugins"),
    Path("/usr/lib/aarch64-linux-gnu/qt6/plugins"),
    Path("/usr/local/lib/qt6/plugins"),
)

_PLUGIN_SUFFIX = "platforminputcontextplugin.so"


@dataclass
class InputMethodStatus:
    requested: str = "auto"
    module: str | None = None
    source: str = "default"
    plugins: dict[str, str] = field(default_factory=dict)
    overlay: str | None = None

    @property
    def label(self) -> str:
        if self.module is None:
            return "未启用"
        if "fcitx" in self.module:
            return "fcitx5"
        return "IBus" if self.module == "ibus" else self.module

    def report(self) -> str:
        lines = [
            f"choice: {self.requested}",
            f"module: {self.module or '未启用'}",
            f"source: {self.source}",
            f"plugin available: {self.plugin_available}",
            f"QT_IM_MODULE={os.environ.get('QT_IM_MODULE', '<unset>')}",
            f"XMODIFIERS={os.environ.get('XMODIFIERS', '<unset>')}",
            f"QT_PLUGIN_PATH={os.environ.get('QT_PLUGIN_PATH', '<unset>')}",
            "plugins:",
        ]
        for name, path in sorted(self.plugins.items()):
            lines.append(f"  {name}: {path}")
        return "\n".join(lines)

    @property
    def plugin_available(self) -> bool:
        if self.module is None:
            return True
        if "fcitx" in self.module:
            return "fcitx5" in self.plugins or "fcitx" in self.plugins
        return self.module in self.plugins


def parse_im_argument(argv: list[str]) -> tuple[list[str], str | None]:
    """Strip ``--im VALUE`` / ``--im=VALUE`` from argv."""
    cleaned: list[str] = []
    requested: str | None = None
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--im":
            if index + 1 < len(argv):
                requested = argv[index + 1]
                index += 2
            else:
                index += 1
            continue
        if argument.startswith("--im="):
            requested = argument.split("=", 1)[1]
            index += 1
            continue
        cleaned.append(argument)
        index += 1
    return cleaned, requested


def _settings_choice() -> str | None:
    try:
        from PySide6.QtCore import QSettings

        value = QSettings("avis-illusio", "docueditor").value("inputMethod", "")
    except Exception:  # pragma: no cover - Qt unavailable
        return None
    text = str(value).strip().lower() if value is not None else ""
    return text if text in CHOICES else None


def _running_process(names: set[str]) -> bool:
    if not Path("/proc").is_dir():
        return False
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return False
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        if comm in names:
            return True
    return False


def detect_module(env: dict[str, str] | None = None) -> str | None:
    env = env if env is not None else os.environ
    modifiers = env.get("XMODIFIERS", "").lower()
    if "fcitx" in modifiers or _running_process({"fcitx5", "fcitx"}):
        return "fcitx"
    if "ibus" in modifiers or _running_process({"ibus-daemon", "ibus"}):
        return "ibus"
    if shutil.which("fcitx5") or shutil.which("fcitx"):
        return "fcitx"
    if shutil.which("ibus-daemon"):
        return "ibus"
    return None


def _pyside_plugin_dir() -> Path | None:
    try:
        import PySide6

        return Path(PySide6.__file__).resolve().parent / "Qt" / "plugins"
    except Exception:  # pragma: no cover - PySide6 unavailable
        return None


def plugin_roots(
    plugin_dirs: list[Path] | None = None,
    env: dict[str, str] | None = None,
) -> list[Path]:
    env = env if env is not None else os.environ
    roots: list[Path] = []
    if plugin_dirs:
        roots.extend(Path(item) for item in plugin_dirs)
    for item in env.get("QT_PLUGIN_PATH", "").split(os.pathsep):
        if item:
            roots.append(Path(item))
    roots.extend(DEFAULT_PLUGIN_DIRS)
    pyside = _pyside_plugin_dir()
    if pyside is not None:
        roots.append(pyside)
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def discover_plugins(
    plugin_dirs: list[Path] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Path]:
    """Find fcitx5 / fcitx / ibus Qt input-context plugins."""
    found: dict[str, Path] = {}
    for root in plugin_roots(plugin_dirs, env):
        directory = root / "platforminputcontexts"
        if not directory.is_dir():
            continue
        try:
            candidates = sorted(directory.glob(f"*{_PLUGIN_SUFFIX}"))
        except OSError:
            continue
        for candidate in candidates:
            name = candidate.name.lower()
            if "fcitx5" in name:
                found.setdefault("fcitx5", candidate)
            elif "fcitx" in name:
                found.setdefault("fcitx", candidate)
            elif "ibus" in name:
                found.setdefault("ibus", candidate)
    return found


def prepare_overlay(plugins: dict[str, Path]) -> Path | None:
    """Create a plugin overlay containing only input-context plugins."""
    if not plugins:
        return None
    overlay = Path(tempfile.mkdtemp(prefix="docueditor-qtplugins-"))
    target = overlay / "platforminputcontexts"
    target.mkdir(parents=True, exist_ok=True)
    for source in plugins.values():
        destination = target / source.name
        try:
            destination.symlink_to(source)
        except OSError:
            try:
                shutil.copy2(source, destination)
            except OSError:
                continue
    atexit.register(shutil.rmtree, overlay, ignore_errors=True)
    return overlay


def configure(
    argv: list[str],
    *,
    requested: str | None = None,
    env: dict[str, str] | None = None,
    settings_value: str | None = None,
    plugin_dirs: list[Path] | None = None,
    running_detector=None,
) -> tuple[list[str], InputMethodStatus]:
    """Configure input-method environment variables before QApplication.

    Returns the argv with ``--im`` removed and a status object for the UI.
    """
    env = env if env is not None else os.environ
    cleaned, cli_choice = parse_im_argument(argv)
    choice = requested or cli_choice or env.get("DOCUEDITOR_IM")
    if choice is None:
        choice = settings_value if settings_value is not None else _settings_choice()
    choice = (choice or "auto").strip().lower()
    if choice not in CHOICES:
        choice = "auto"

    status = InputMethodStatus(requested=choice)
    if not sys.platform.startswith("linux"):
        status.source = "unsupported"
        return cleaned, status

    if choice == "auto":
        current = env.get("QT_IM_MODULE", "").strip()
        if current:
            status.module = current
            status.source = "environment"
        else:
            detected = (
                running_detector() if running_detector is not None else detect_module(env)
            )
            status.module = detected
            status.source = "detected" if detected else "default"
    elif choice == "none":
        status.module = None
        status.source = "disabled"
    else:
        status.module = MODULE_FOR_CHOICE.get(choice, choice)
        status.source = "choice"

    if status.module:
        env["QT_IM_MODULE"] = status.module
        if "fcitx" in status.module:
            env.setdefault("XMODIFIERS", "@im=fcitx")
        elif status.module == "ibus":
            env.setdefault("XMODIFIERS", "@im=ibus")
    else:
        env.pop("QT_IM_MODULE", None)

    plugins = discover_plugins(plugin_dirs, env)
    status.plugins = {name: str(path) for name, path in plugins.items()}
    overlay = prepare_overlay(plugins)
    if overlay is not None:
        status.overlay = str(overlay)
        existing = env.get("QT_PLUGIN_PATH", "")
        env["QT_PLUGIN_PATH"] = str(overlay) + (os.pathsep + existing if existing else "")
    return cleaned, status


def current_status() -> InputMethodStatus:
    """Status for the UI (does not modify the environment)."""
    choice = _settings_choice() or "auto"
    module = os.environ.get("QT_IM_MODULE", "").strip() or None
    plugins = discover_plugins()
    return InputMethodStatus(
        requested=choice,
        module=module,
        source="runtime",
        plugins={name: str(path) for name, path in plugins.items()},
    )
