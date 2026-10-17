import sys
from pathlib import Path

import pytest

from docueditor import input_method


def make_plugins(tmp_path: Path) -> Path:
    root = tmp_path / "plugins"
    directory = root / "platforminputcontexts"
    directory.mkdir(parents=True)
    for name in (
        "libfcitx5platforminputcontextplugin.so",
        "libibusplatforminputcontextplugin.so",
    ):
        (directory / name).write_bytes(b"")
    return root


def test_parse_im_argument():
    assert input_method.parse_im_argument(["app", "--im", "fcitx5", "site"]) == (
        ["app", "site"],
        "fcitx5",
    )
    assert input_method.parse_im_argument(["app", "--im=ibus"]) == (["app"], "ibus")
    assert input_method.parse_im_argument(["app", "--im"]) == (["app"], None)


def test_configure_explicit_fcitx5(tmp_path):
    plugins = make_plugins(tmp_path)
    env: dict[str, str] = {}
    cleaned, status = input_method.configure(
        ["app", "--im", "fcitx5"],
        env=env,
        plugin_dirs=[plugins],
        settings_value="auto",
    )
    assert cleaned == ["app"]
    assert status.module == "fcitx"
    assert status.source == "choice"
    assert env["QT_IM_MODULE"] == "fcitx"
    assert env["XMODIFIERS"] == "@im=fcitx"
    assert "fcitx5" in status.plugins
    assert status.plugin_available
    assert status.overlay is not None
    overlay = Path(status.overlay)
    assert (overlay / "platforminputcontexts" / "libfcitx5platforminputcontextplugin.so").exists()
    assert env["QT_PLUGIN_PATH"].startswith(str(overlay))


def test_auto_keeps_environment_module(tmp_path):
    env = {"QT_IM_MODULE": "ibus", "XMODIFIERS": "@im=ibus"}
    _, status = input_method.configure(
        ["app"],
        env=env,
        plugin_dirs=[make_plugins(tmp_path)],
        settings_value="auto",
    )
    assert status.module == "ibus"
    assert status.source == "environment"
    assert env["QT_IM_MODULE"] == "ibus"


def test_auto_detects_running_fcitx5(tmp_path):
    env: dict[str, str] = {}
    _, status = input_method.configure(
        ["app"],
        env=env,
        plugin_dirs=[make_plugins(tmp_path)],
        settings_value="auto",
        running_detector=lambda: "fcitx",
    )
    assert status.module == "fcitx"
    assert status.source == "detected"
    assert env["XMODIFIERS"] == "@im=fcitx"


def test_none_disables_module():
    env = {"QT_IM_MODULE": "fcitx"}
    _, status = input_method.configure(
        ["app"], requested="none", env=env, plugin_dirs=[], settings_value="auto"
    )
    assert status.module is None
    assert "QT_IM_MODULE" not in env


def test_settings_choice_is_used(tmp_path):
    env: dict[str, str] = {}
    _, status = input_method.configure(
        ["app"],
        env=env,
        plugin_dirs=[make_plugins(tmp_path)],
        settings_value="ibus",
    )
    assert status.module == "ibus"
    assert status.source == "choice"
