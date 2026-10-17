"""Import planning and execution shared by every importer.

The default mode is *append*: existing files are never overwritten and
sidebar positions continue after the highest existing number.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..frontmatter import FrontMatter
from ..project import DocusaurusProject
from ..utils import slugify, unique_path, write_text

APPEND = "append"
REPLACE = "replace"


@dataclass
class ImportItem:
    title: str
    body: str
    rel_dir: str = ""
    position: int | None = None
    extras: dict[str, object] = field(default_factory=dict)

    def filename(self) -> str:
        return f"{slugify(self.title, fallback='untitled')}.md"


@dataclass
class ImportPlan:
    source: Path
    kind: str
    items: list[ImportItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return f"{self.kind} · {len(self.items)} 篇 · {len(self.warnings)} 条警告"


@dataclass
class PlannedFile:
    rel: str
    title: str
    position: int
    action: str  # create | overwrite
    source_note: str = ""


@dataclass
class ImportResult:
    created: list[str] = field(default_factory=list)
    overwritten: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    backup_root: Path | None = None


def _safe_rel_dir(rel_dir: str) -> str:
    parts = []
    for part in Path(rel_dir).parts if rel_dir else []:
        if part in {"", ".", ".."} or part.startswith("."):
            continue
        parts.append(slugify(part, fallback="section"))
    return "/".join(parts)


def plan_import(
    project: DocusaurusProject,
    plan: ImportPlan,
    mode: str = APPEND,
) -> list[PlannedFile]:
    if project.docs_dir is None:
        raise ValueError("项目尚未加载")
    existing = {entry.rel for entry in project.entries}
    next_positions: dict[str, int] = {}
    planned: list[PlannedFile] = []
    used: set[str] = set()
    for item in plan.items:
        rel_dir = _safe_rel_dir(item.rel_dir)
        directory = project.docs_dir / rel_dir if rel_dir else project.docs_dir
        stem = slugify(item.title, fallback="untitled")
        rel = f"{rel_dir}/{stem}.md" if rel_dir else f"{stem}.md"
        action = "create"
        if rel in existing or rel in used:
            if mode == REPLACE:
                action = "overwrite"
            else:
                candidate = unique_path(directory, stem, ".md")
                rel = (
                    f"{rel_dir}/{candidate.name}" if rel_dir else candidate.name
                )
        used.add(rel)
        if item.position is not None:
            position = item.position
        else:
            if rel_dir not in next_positions:
                next_positions[rel_dir] = project.next_position(rel_dir)
            position = next_positions[rel_dir]
            next_positions[rel_dir] += 1
        planned.append(
            PlannedFile(
                rel=rel,
                title=item.title,
                position=position,
                action=action,
                source_note=item.extras.get("source", "") if item.extras else "",
            )
        )
    return planned


def _document_text(title: str, position: int, body: str) -> str:
    header = FrontMatter()
    text = header.with_overrides(
        {"title": title, "sidebar_position": position}
    )
    body = body.strip("\n")
    if not body:
        return text.rstrip("\n") + "\n"
    return text.rstrip("\n") + "\n\n" + body + "\n"


def execute_import(
    project: DocusaurusProject,
    plan: ImportPlan,
    mode: str = APPEND,
    *,
    dry_run: bool = False,
) -> ImportResult:
    if project.docs_dir is None:
        raise ValueError("项目尚未加载")
    planned = plan_import(project, plan, mode)
    result = ImportResult(warnings=list(plan.warnings))
    if dry_run:
        return result

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = project.root / ".docueditor-backup" / stamp
    for item, target in zip(plan.items, planned):
        path = project.docs_dir / target.rel
        if target.action == "overwrite" and path.exists():
            backup = backup_root / target.rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            result.backup_root = backup_root
            result.overwritten.append(target.rel)
        else:
            result.created.append(target.rel)
        write_text(path, _document_text(target.title, target.position, item.body))
    project.scan()
    return result


def apply_import(
    project: DocusaurusProject,
    plan: ImportPlan,
    mode: str = APPEND,
    *,
    dry_run: bool = False,
) -> tuple[list[PlannedFile], ImportResult]:
    planned = plan_import(project, plan, mode)
    result = execute_import(project, plan, mode, dry_run=dry_run)
    return planned, result
