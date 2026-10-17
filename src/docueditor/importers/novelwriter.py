"""Import a novelwriter project (``*.nwd``) into a Docusaurus docs tree."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..utils import natural_key, read_text, slugify
from .base import ImportItem, ImportPlan

PROJECT_FILE = "nwProject.nwx"
TEXT_SUFFIXES = (".txt", ".md", ".markdown")
_NOTE_TYPES = {"NOTE"}
_NOTE_CLASSES = {"NOTE"}

_FILENAME_INDEX = re.compile(r"^\s*\d+\s*[-_.、 ]\s*")


def load(path: str | Path) -> ImportPlan:
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    if source.is_file():
        if source.name == PROJECT_FILE:
            return _load_xml_project(source.parent)
        if source.suffix.lower() in TEXT_SUFFIXES:
            return _load_single(source)
        raise ValueError(f"无法识别的 novelwriter 输入：{source.name}")
    if (source / PROJECT_FILE).is_file():
        return _load_xml_project(source)
    if source.suffix.lower() == ".nwd":
        raise FileNotFoundError(f"项目目录中缺少 {PROJECT_FILE}：{source}")
    return _load_folder(source)


# --------------------------------------------------------------- projects
def _load_xml_project(root: Path) -> ImportPlan:
    plan = ImportPlan(source=root, kind="Novelwriter")
    xml_path = root / PROJECT_FILE
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        raise ValueError(f"{PROJECT_FILE} 解析失败：{exc}") from exc
    content = None
    for element in tree.getroot().iter():
        if element.tag.lower() == "content":
            content = element
            break
    if content is None:
        plan.warnings.append("项目文件里没有 <content> 节点")
        return plan
    items = list(content)
    by_handle: dict[str, ET.Element] = {}
    for element in items:
        handle = element.get("handle")
        if handle:
            by_handle[handle] = element
    items.sort(key=lambda e: _int_attr(e, "order"))
    for element in items:
        kind = (element.get("type") or "").upper()
        if kind in _NOTE_TYPES:
            plan.warnings.append(f"跳过笔记：{element.get('title', '(无标题)')}")
            continue
        if kind and kind != "DOC":
            continue
        title = (element.get("title") or "").strip() or "未命名"
        handle = element.get("handle") or ""
        doc_path = _document_path(root, handle)
        if doc_path is None:
            plan.warnings.append(f"找不到正文文件：{title} ({handle})")
            continue
        body = _clean_text(read_text(doc_path), title)
        rel_dir = _parent_path(element, by_handle)
        plan.items.append(
            ImportItem(
                title=title,
                body=body,
                rel_dir=rel_dir,
                extras={"source": str(doc_path.relative_to(root))},
            )
        )
    if not plan.items:
        plan.warnings.append("项目里没有可导入的文档")
    return plan


def _document_path(root: Path, handle: str) -> Path | None:
    if not handle:
        return None
    content_dir = root / "content"
    for suffix in TEXT_SUFFIXES:
        candidate = content_dir / f"{handle}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def _int_attr(element: ET.Element, name: str) -> int:
    try:
        return int(element.get(name, "0"))
    except (TypeError, ValueError):
        return 0


def _parent_path(element: ET.Element, by_handle: dict[str, ET.Element]) -> str:
    parts: list[str] = []
    parent = element.get("parent")
    guard = 0
    while parent and parent != "None" and guard < 8:
        guard += 1
        ancestor = by_handle.get(parent)
        if ancestor is None:
            break
        kind = (ancestor.get("type") or "").upper()
        if kind == "DOC":
            title = (ancestor.get("title") or "").strip()
            if title:
                parts.append(slugify(title))
        parent = ancestor.get("parent")
    parts.reverse()
    return "/".join(parts)


def _clean_text(text: str, title: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned: list[str] = []
    in_comment = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("%%"):
            in_comment = not in_comment
            continue
        if in_comment:
            continue
        if stripped.startswith("%"):
            continue
        if stripped.startswith("@") and ":" in stripped:
            continue
        if re.match(r"^@\w+\s*$", stripped):
            continue
        cleaned.append(line)
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    if cleaned and cleaned[0].strip() == f"# {title}".strip():
        cleaned.pop(0)
        while cleaned and not cleaned[0].strip():
            cleaned.pop(0)
    body = "\n".join(cleaned).strip("\n")
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body


# ----------------------------------------------------------------- folders
def _load_folder(root: Path) -> ImportPlan:
    plan = ImportPlan(source=root, kind="Novelwriter")
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in TEXT_SUFFIXES
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
    ]
    files.sort(key=lambda p: natural_key(str(p.relative_to(root))))
    for path in files:
        text = read_text(path)
        title, body = _split_title(text, path.stem)
        rel = path.parent.relative_to(root)
        rel_dir = "/".join(slugify(part) for part in rel.parts if part not in ("", "."))
        plan.items.append(
            ImportItem(
                title=title,
                body=_clean_text(body, title),
                rel_dir=rel_dir,
                extras={"source": str(path.relative_to(root))},
            )
        )
    if not plan.items:
        plan.warnings.append("文件夹里没有 .txt / .md 文件")
    return plan


def _load_single(path: Path) -> ImportPlan:
    plan = ImportPlan(source=path, kind="Novelwriter")
    text = read_text(path)
    sections = _split_sections(text)
    if len(sections) <= 1:
        title, body = _split_title(text, path.stem)
        plan.items.append(ImportItem(title=title, body=_clean_text(body, title)))
    else:
        for title, body in sections:
            plan.items.append(ImportItem(title=title, body=_clean_text(body, title)))
    return plan


def _split_title(text: str, fallback: str) -> tuple[str, str]:
    lines = text.replace("\r\n", "\n").split("\n")
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            return stripped[2:].strip() or fallback, "\n".join(lines[index + 1 :])
        break
    title = _FILENAME_INDEX.sub("", fallback).strip() or fallback
    return title, text


def _split_sections(text: str) -> list[tuple[str, str]]:
    normalised = text.replace("\r\n", "\n")
    parts = re.split(r"(?m)^# ", normalised)
    if len(parts) <= 1:
        return []
    sections: list[tuple[str, str]] = []
    for part in parts[1:]:
        lines = part.split("\n")
        title = lines[0].strip() or "未命名"
        sections.append((title, "\n".join(lines[1:])))
    return sections
