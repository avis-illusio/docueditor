"""Reading and writing Docusaurus YAML front matter.

The editor deliberately keeps the original header lines so that unknown,
nested or hand-formatted keys survive a round-trip.  Only keys that are
explicitly overridden are rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

DELIMITER = "---"

_TRUE = {"true", "yes", "on"}
_FALSE = {"false", "no", "off"}


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        quote = value[0]
        inner = value[1:-1]
        if quote == '"':
            return (
                inner.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )
        return inner.replace("''", "'")
    return value


def _coerce(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_coerce(part) for part in _split_inline_list(inner)]
    lowered = text.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    if lowered in {"null", "~"}:
        return None
    try:
        if text.startswith(("0x", "0o", "0b")):
            return int(text, 0)
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return _strip_quotes(text)


def _split_inline_list(inner: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            continue
        if ch == ",":
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p != ""]


def format_scalar(value: Any) -> str:
    """Render a Python value as a single-line YAML scalar."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "":
        return '""'
    needs_quotes = (
        text != text.strip()
        or text.lower() in _TRUE | _FALSE | {"null", "~"}
        or any(ch in text for ch in ":#[]{},&*!|>'\"%@`\n\t")
        or text.startswith(("-", "?", " "))
    )
    if not needs_quotes:
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    return f'"{escaped}"'


def format_value(key: str, value: Any) -> list[str]:
    """Render a key/value pair as YAML lines (lists use block style)."""
    if isinstance(value, (list, tuple)):
        if not value:
            return [f"{key}: []"]
        lines = [f"{key}:"]
        for item in value:
            lines.append(f"  - {format_scalar(item)}")
        return lines
    return [f"{key}: {format_scalar(value)}"]


def _key_of(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or ":" not in stripped:
        return None
    if line[:1].isspace():
        return None
    key = stripped.split(":", 1)[0].strip()
    if not key or " " in key:
        return None
    return key


@dataclass
class FrontMatter:
    """A parsed front matter block plus the untouched body."""

    lines: list[str] = field(default_factory=list)
    body: str = ""
    has_header: bool = False
    values: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def with_overrides(self, overrides: dict[str, Any]) -> str:
        """Return the full document with *overrides* applied to the header.

        ``None`` removes a key.  New keys are appended.  Unrelated lines,
        comments and nested blocks are preserved verbatim.
        """
        lines = list(self.lines)
        for key, value in overrides.items():
            start, end = _find_block(lines, key)
            rendered: list[str] = [] if value is None else format_value(key, value)
            if start is None:
                if value is None:
                    continue
                lines.extend(rendered)
            else:
                lines[start:end] = rendered
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines and not overrides:
            return self.body
        header = [DELIMITER, *lines, DELIMITER, ""]
        return "\n".join(header) + self.body


def _find_block(lines: list[str], key: str) -> tuple[int | None, int]:
    for index, line in enumerate(lines):
        if _key_of(line) == key:
            end = index + 1
            while end < len(lines):
                candidate = lines[end]
                if candidate.strip() == "" or candidate[:1].isspace():
                    # A blank line only belongs to the block if a nested
                    # indented line follows.
                    if candidate.strip() == "":
                        lookahead = end + 1
                        while lookahead < len(lines) and lines[lookahead].strip() == "":
                            lookahead += 1
                        if lookahead < len(lines) and lines[lookahead][:1].isspace():
                            end = lookahead
                            continue
                        break
                    end += 1
                    continue
                break
            return index, end
    return None, 0


def _parse_values(lines: Iterable[str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    materialised = list(lines)
    index = 0
    while index < len(materialised):
        line = materialised[index]
        key = _key_of(line)
        index += 1
        if key is None:
            continue
        raw = line.split(":", 1)[1].strip()
        if raw:
            values[key] = _coerce(raw)
            continue
        block: list[str] = []
        while index < len(materialised):
            candidate = materialised[index]
            if candidate.strip() == "":
                block.append(candidate)
                index += 1
                continue
            if not candidate[:1].isspace():
                break
            block.append(candidate)
            index += 1
        while block and not block[-1].strip():
            block.pop()
        items = [entry.strip() for entry in block if entry.strip().startswith("- ")]
        if items and len(items) == len([entry for entry in block if entry.strip()]):
            values[key] = [_coerce(entry[2:]) for entry in items]
        else:
            values[key] = "\n".join(block).strip() if block else None
    return values


def split(text: str) -> FrontMatter:
    """Split ``text`` into front matter and body."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalised.startswith(f"{DELIMITER}\n") and normalised.strip() != DELIMITER:
        return FrontMatter(body=normalised)
    lines = normalised.split("\n")
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == DELIMITER:
            closing = index
            break
    if closing is None:
        return FrontMatter(body=normalised)
    header = lines[1:closing]
    body = "\n".join(lines[closing + 1 :])
    return FrontMatter(
        lines=header,
        body=body,
        has_header=True,
        values=_parse_values(header),
    )


def join(front_matter: FrontMatter, body: str | None = None) -> str:
    """Reassemble a document, optionally replacing the body."""
    if body is not None:
        front_matter = FrontMatter(
            lines=front_matter.lines,
            body=body,
            has_header=front_matter.has_header,
            values=front_matter.values,
        )
    if not front_matter.has_header and not front_matter.lines:
        return front_matter.body
    header = [DELIMITER, *front_matter.lines, DELIMITER, ""]
    return "\n".join(header) + front_matter.body
