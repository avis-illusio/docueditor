"""Text-level editing of ``docusaurus.config.js`` and ``package.json``.

Docusaurus configs are JavaScript, not JSON, so we only touch the literal
string values of well-known top-level keys.  Comments, formatting and any
other code stay untouched.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .utils import read_text, write_text

SITE_KEYS = (
    "title",
    "tagline",
    "url",
    "baseUrl",
    "organizationName",
    "projectName",
)

KEY_LABELS = {
    "title": "站点标题",
    "tagline": "副标题",
    "url": "站点 URL",
    "baseUrl": "基础路径",
    "organizationName": "组织名（GitHub）",
    "projectName": "项目名（GitHub）",
}

_STRING_VALUE = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z_$][\w$]*)\s*:\s*"
    r"(?P<quote>['\"`])(?P<value>(?:\\.|(?!\3).)*)\3(?P<tail>\s*,?\s*)$"
)


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\'", "'")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )


def _quote(value: str) -> tuple[str, str]:
    if "'" not in value:
        return "'", value.replace("\\", "\\\\").replace("\n", "\\n")
    if '"' not in value:
        return '"', value.replace("\\", "\\\\").replace("\n", "\\n")
    return "`", value.replace("\\", "\\\\").replace("`", "\\`").replace("\n", "\\n")


def read_site_config(path: Path) -> dict[str, str]:
    """Return the string-valued top-level site keys found in *path*."""
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in read_text(path).splitlines():
        match = _STRING_VALUE.match(line)
        if not match:
            continue
        key = match.group("key")
        if key in SITE_KEYS and key not in result:
            result[key] = _unescape(match.group("value"))
    return result


def update_site_config(path: Path, values: dict[str, str]) -> list[str]:
    """Rewrite the given keys in place and return the keys that changed."""
    if not path.is_file():
        raise FileNotFoundError(path)
    lines = read_text(path).splitlines()
    changed: list[str] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        match = _STRING_VALUE.match(line)
        if not match:
            continue
        key = match.group("key")
        if key not in values or key in seen:
            continue
        seen.add(key)
        old = _unescape(match.group("value"))
        new = values[key]
        if old == new:
            continue
        quote, escaped = _quote(new)
        lines[index] = (
            f"{match.group('indent')}{key}: {quote}{escaped}{quote}{match.group('tail')}"
        )
        changed.append(key)
    if changed:
        write_text(path, "\n".join(lines) + "\n")
    return changed


def read_package_json(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        key: str(data[key])
        for key in ("name", "version", "description")
        if key in data and isinstance(data[key], (str, int, float))
    }


def update_package_json(path: Path, values: dict[str, str]) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise ValueError(f"package.json 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("package.json 顶层不是对象")
    changed: list[str] = []
    for key, value in values.items():
        if key in {"name", "version", "description"} and data.get(key) != value:
            data[key] = value
            changed.append(key)
    if changed:
        write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return changed
