"""Small shared helpers for Docueditor."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

_INVALID_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_DASHES = re.compile(r"-{2,}")
_SPACES = re.compile(r"\s+")


def natural_key(text: str) -> list[object]:
    """Sort key that orders ``chapter2`` before ``chapter10``."""
    parts = re.split(r"(\d+)", text.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def slugify(text: str, fallback: str = "untitled") -> str:
    """Turn a title into a safe, readable filename stem.

    CJK characters are preserved on purpose: Docusaurus serves them fine and
    users who write Chinese documentation expect Chinese file names.
    """
    normalised = unicodedata.normalize("NFKC", text).strip().lower()
    normalised = _INVALID_FILENAME.sub("", normalised)
    normalised = _SPACES.sub("-", normalised)
    normalised = _DASHES.sub("-", normalised).strip("-.")
    normalised = normalised.replace(" ", "-")
    return normalised or fallback


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """Return a non-existing path ``stem+suffix`` under *directory*."""
    candidate = directory / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def relative_posix(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def word_count(text: str) -> int:
    """Rough word count: CJK characters count individually."""
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))
    latin = len(re.findall(r"[A-Za-z0-9_]+", text))
    return cjk + latin
