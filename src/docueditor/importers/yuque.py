"""Import Yuque (语雀) exports: folder, ZIP or merged single file."""

from __future__ import annotations

import html
import re
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from ..utils import natural_key, read_text, slugify
from .base import ImportItem, ImportPlan

TEXT_SUFFIXES = (".md", ".markdown", ".txt")
_SKIP_NAMES = {"__MACOSX", ".DS_Store", "Thumbs.db"}
_INDEX_PREFIX = re.compile(r"^\s*(?:\d+[\s._、-]+)?(?P<title>.+)$")
_INLINE_HTML = re.compile(r"<(table|img|br|p|div|span|strong|b|em|i|code|a|ul|ol|li|h[1-6])\b", re.I)


def load(path: str | Path) -> ImportPlan:
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    if source.is_file() and source.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory(prefix="docueditor-yuque-") as tmp:
            extract_dir = Path(tmp)
            _safe_extract(source, extract_dir)
            plan = _load_folder(extract_dir)
            plan.source = source
            return plan
    if source.is_file():
        return _load_single(source)
    return _load_folder(source)


def _safe_extract(archive: Path, target: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            name = member.filename
            if name.startswith("/") or ".." in Path(name).parts:
                continue
            if any(part in _SKIP_NAMES for part in Path(name).parts):
                continue
            zf.extract(member, target)


def _collect(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in _SKIP_NAMES or part.startswith(".") for part in rel_parts):
            continue
        files.append(path)
    files.sort(key=lambda p: natural_key(str(p.relative_to(root))))
    return files


def _common_top(root: Path, files: list[Path]) -> str | None:
    if not files:
        return None
    tops = {path.relative_to(root).parts[0] for path in files if len(path.relative_to(root).parts) > 1}
    if len(tops) == 1:
        return tops.pop()
    return None


def _load_folder(root: Path) -> ImportPlan:
    plan = ImportPlan(source=root, kind="语雀")
    files = _collect(root)
    if not files:
        plan.warnings.append("没有找到 Markdown 文件")
        return plan
    top = _common_top(root, files)
    for path in files:
        rel_parts = list(path.relative_to(root).parts)
        if top and rel_parts and rel_parts[0] == top:
            rel_parts = rel_parts[1:]
        rel_dir = "/".join(slugify(part) for part in rel_parts[:-1])
        text = read_text(path)
        title, body = _title_and_body(text, path.stem)
        converted = convert(body)
        if not converted.strip():
            plan.warnings.append(f"跳过空文档：{path.name}")
            continue
        if "cdn.nlark.com" in converted or "yuque.com" in converted:
            plan.warnings.append(f"含语雀远程图片，需手动下载迁移：{path.name}")
        plan.items.append(
            ImportItem(
                title=title,
                body=converted,
                rel_dir=rel_dir,
                extras={"source": str(path.relative_to(root))},
            )
        )
    return plan


def _load_single(path: Path) -> ImportPlan:
    plan = ImportPlan(source=path, kind="语雀")
    text = read_text(path)
    sections = _split_h1(text)
    if len(sections) >= 2:
        for title, body in sections:
            plan.items.append(ImportItem(title=title, body=convert(body)))
        return plan
    title, body = _title_and_body(text, path.stem)
    plan.items.append(ImportItem(title=title, body=convert(body)))
    return plan


def _title_and_body(text: str, fallback: str) -> tuple[str, str]:
    lines = text.replace("\r\n", "\n").split("\n")
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            return stripped[2:].strip() or fallback, "\n".join(lines[index + 1 :])
        break
    match = _INDEX_PREFIX.match(fallback)
    title = (match.group("title") if match else fallback).strip() or fallback
    return title, text


def _split_h1(text: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?m)^# ", text.replace("\r\n", "\n"))
    if len(parts) <= 2:
        return []
    sections: list[tuple[str, str]] = []
    for part in parts[1:]:
        lines = part.split("\n")
        title = lines[0].strip() or "未命名"
        sections.append((title, "\n".join(lines[1:])))
    return sections


# ------------------------------------------------------------------ convert
def convert(text: str) -> str:
    """Convert Yuque's HTML fragments to Markdown, leaving Markdown intact."""
    if not _INLINE_HTML.search(text):
        return text.strip("\n")
    parser = _YuqueHTMLParser()
    parser.feed(text)
    parser.close()
    result = "".join(parser.output)
    # Collapse the blank lines the HTML walker tends to create.
    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip("\n")


class _YuqueHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.table_rows: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.link_stack: list[str] = []
        self.link_text: list[str] = []

    # -- helpers
    def _write(self, text: str) -> None:
        if self.cell is not None:
            self.cell.append(text)
        elif self.link_stack:
            self.link_text.append(text)
        else:
            self.output.append(text)

    def _flush_table(self) -> None:
        if not self.table_rows:
            self.table_rows = None
            return
        rows = [row for row in self.table_rows if any(cell.strip() for cell in row)]
        if not rows:
            self.table_rows = None
            return
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        lines = ["| " + " | ".join(cell.strip().replace("\n", "<br>") for cell in rows[0]) + " |"]
        lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
        for row in rows[1:]:
            lines.append("| " + " | ".join(cell.strip().replace("\n", "<br>") for cell in row) + " |")
        block = "\n".join(lines)
        if self.output and not self.output[-1].endswith("\n"):
            self.output.append("\n\n")
        self.output.append(block + "\n\n")
        self.table_rows = None

    # -- HTMLParser hooks
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            self._flush_table()
            self.table_rows = []
            return
        if tag == "tr" and self.table_rows is not None:
            self.row = []
            return
        if tag in {"td", "th"} and self.row is not None:
            self.cell = []
            return
        if self.table_rows is not None:
            return
        if tag == "br":
            self._write("\n")
        elif tag in {"p", "div", "section"}:
            if self.output and not self.output[-1].endswith("\n"):
                self.output.append("\n\n")
        elif tag in {"strong", "b"}:
            self._write("**")
        elif tag in {"em", "i"}:
            self._write("*")
        elif tag == "code":
            self._write("`")
        elif tag == "a":
            self.link_stack.append(attributes.get("href") or "")
            self.link_text = []
        elif tag == "img":
            src = attributes.get("src") or ""
            alt = attributes.get("alt") or ""
            if src:
                self._write(f"![{alt}]({src})")
        elif tag == "li":
            self._write("- ")
        elif tag in {"ul", "ol"}:
            if self.output and not self.output[-1].endswith("\n"):
                self.output.append("\n")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag[1])
            if self.output and not self.output[-1].endswith("\n"):
                self.output.append("\n\n")
            self._write("#" * level + " ")
        elif tag == "hr":
            self._write("\n---\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._flush_table()
            return
        if tag == "tr" and self.table_rows is not None:
            if self.row is not None:
                self.table_rows.append(self.row)
            self.row = None
            return
        if tag in {"td", "th"} and self.cell is not None:
            if self.row is not None:
                self.row.append("".join(self.cell))
            self.cell = None
            return
        if self.table_rows is not None:
            return
        if tag in {"strong", "b"}:
            self._write("**")
        elif tag in {"em", "i"}:
            self._write("*")
        elif tag == "code":
            self._write("`")
        elif tag == "a" and self.link_stack:
            href = self.link_stack.pop()
            label = "".join(self.link_text).strip()
            self.link_text = []
            self.output.append(f"[{label}]({href})" if href else label)
        elif tag in {"p", "div", "section", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._write("\n")

    def handle_data(self, data: str) -> None:
        self._write(html.unescape(data))
