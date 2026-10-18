import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*arguments: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "docueditor", *arguments],
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )


def test_help_does_not_load_qt():
    result = run_cli("--help")
    assert result.returncode == 0
    assert "用法" in result.stdout
    assert "Fontconfig" not in result.stderr


def test_version_does_not_load_qt():
    result = run_cli("--version")
    assert result.returncode == 0
    assert "Docueditor" in result.stdout
    assert "Fontconfig" not in result.stderr
