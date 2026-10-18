"""Protect MDX constructs that a rich-text Markdown round-trip would mangle.

Qt's Markdown importer/exporter understands CommonMark and a GitHub dialect,
but it does not know about ``import`` statements, JSX components or Docusaurus
admonition directives.  Before loading text into the WYSIWYG editor we swap
those blocks for inert tokens, and before saving we swap them back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TOKEN_PREFIX = "DOCUEDITORTOKEN"

_FENCE = re.compile(r"^(?P<fence>`{3,}|~{3,})\s*(?P<info>[^\n]*)$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]*-{3,}[\s:|-]*\|?\s*$")
_IMPORT_EXPORT = re.compile(r"^\s*(?:import|export)\s")
_JSX_START = re.compile(r"^\s*<([A-Za-z][\w.:-]*)(?=[\s/>])")
_ADMONITION = re.compile(r"^\s*:::\s*(?P<kind>[\w-]*)\s*$")
_HTML_COMMENT_START = re.compile(r"^\s*<!--")

_CJK = re.compile(r"[\u4e00-\u9fff]")


@dataclass
class Protected:
    text: str
    tokens: dict[str, str] = field(default_factory=dict)

    def restore(self, masked: str) -> str:
        for token, original in self.tokens.items():
            masked = masked.replace(token, original)
        return masked


def _token(index: int) -> str:
    return f"{TOKEN_PREFIX}{index:04d}"


def protect(text: str) -> Protected:
    """Replace MDX/JSX/fenced-code blocks with tokens."""
    if not text:
        return Protected(text or "")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    tokens: dict[str, str] = {}
    out: list[str] = []
    index = 0

    def emit(block_lines: list[str]) -> None:
        nonlocal index
        token = _token(index)
        index += 1
        tokens[token] = "\n".join(block_lines)
        if out and out[-1].strip():
            out.append("")
        out.append(token)
        if i < len(lines) and lines[i].strip():
            out.append("")

    i = 0
    while i < len(lines):
        line = lines[i]

        # Fenced code blocks are left to Qt, but their content must not be
        # scanned for JSX/imports/admonitions.
        fence_match = _FENCE.match(line)
        if fence_match:
            fence = fence_match.group("fence")
            marker = fence[0]
            block = [line]
            i += 1
            while i < len(lines):
                block.append(lines[i])
                stripped = lines[i].strip()
                if stripped.startswith(marker * len(fence)) and stripped.strip(marker) == "":
                    i += 1
                    break
                i += 1
            out.extend(block)
            continue

        # import / export statements (single line or a small continuation).
        if _IMPORT_EXPORT.match(line):
            block = [line]
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(("#", "-", "*", ">")):
                block.append(lines[i])
                i += 1
            emit(block)
            continue

        # Docusaurus admonitions / directives.
        admonition = _ADMONITION.match(line)
        if admonition:
            block = [line]
            i += 1
            while i < len(lines):
                block.append(lines[i])
                if _ADMONITION.match(lines[i]):
                    i += 1
                    break
                i += 1
            emit(block)
            continue

        # HTML comments.
        if _HTML_COMMENT_START.match(line):
            block = [line]
            i += 1
            while i < len(lines):
                block.append(lines[i])
                if "-->" in lines[i]:
                    i += 1
                    break
                i += 1
            emit(block)
            continue

        # JSX blocks / self-closing components.
        jsx = _JSX_START.match(line)
        if jsx:
            tag = jsx.group(1)
            block = [line]
            i += 1
            # Self-closing or a single-line opening tag?
            if not re.search(r"/>\s*$", line) and not re.search(r"</", line):
                closing = re.compile(rf"</\s*{re.escape(tag)}\s*>")
                while i < len(lines):
                    block.append(lines[i])
                    if closing.search(lines[i]):
                        i += 1
                        break
                    i += 1
            emit(block)
            continue

        out.append(line)
        i += 1

    return Protected("\n".join(out), tokens)


def restore(masked: str, protected: Protected) -> str:
    return protected.restore(masked)


def has_protected(protected: Protected) -> bool:
    return bool(protected.tokens)


def describe_tokens(protected: Protected) -> list[str]:
    """Human readable labels for the protected blocks (for UI hints)."""
    labels: list[str] = []
    for token, block in protected.tokens.items():
        first = block.splitlines()[0].strip() if block else ""
        if first.startswith(("import", "export")):
            labels.append(f"{token}: ESM 语句")
        elif first.startswith(":::"):
            labels.append(f"{token}: 指令块")
        elif first.startswith("<!--"):
            labels.append(f"{token}: HTML 注释")
        else:
            labels.append(f"{token}: JSX 组件")
    return labels
