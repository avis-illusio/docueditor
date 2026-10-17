"""The Docusaurus project model.

Everything that touches the file system lives here so the GUI stays thin and
the behaviour can be unit tested without a display server.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter
from .utils import natural_key, read_text, relative_posix, slugify, unique_path, write_text

CONFIG_NAMES = (
    "docusaurus.config.js",
    "docusaurus.config.ts",
    "docusaurus.config.mjs",
    "docusaurus.config.cjs",
)
DOC_SUFFIXES = (".md", ".mdx")

_DOCS_PATH_RE = re.compile(
    r"docs\s*:\s*\{[^{}]*?path\s*:\s*['\"]([^'\"]+)['\"]", re.S
)
_SIDEBARS_PATH_RE = re.compile(
    r"sidebar(?:s)?\s*:\s*\{[^{}]*?path\s*:\s*['\"]([^'\"]+)['\"]", re.S
)


class ProjectError(RuntimeError):
    """Raised when the directory is not a usable Docusaurus project."""


@dataclass
class DocEntry:
    path: Path
    rel: str
    title: str
    position: int | None = None
    doc_id: str | None = None
    front_matter: frontmatter.FrontMatter = field(default_factory=frontmatter.FrontMatter)
    body: str = ""

    @property
    def suffix(self) -> str:
        return self.path.suffix

    def sort_key(self) -> tuple[int, list[object]]:
        position = self.position if self.position is not None else 10**6
        return (position, natural_key(self.rel))


@dataclass
class DirEntry:
    """A folder that participates in the sidebar (via _category_.json)."""

    path: Path
    rel: str
    label: str
    position: int | None = None
    link: dict | None = None
    has_category: bool = False

    def sort_key(self) -> tuple[int, list[object]]:
        position = self.position if self.position is not None else 10**6
        return (position, natural_key(self.label))


@dataclass
class TreeNode:
    """A document or folder in one sidebar level."""

    kind: str  # "doc" | "dir"
    rel: str
    label: str
    position: int | None = None
    children: list["TreeNode"] = field(default_factory=list)
    entry: DocEntry | None = None
    directory: DirEntry | None = None
    container: bool = False
    index_rel: str | None = None


class DocusaurusProject:
    """A folder containing a Docusaurus site."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.config_path: Path | None = None
        self.docs_dir: Path | None = None
        self.sidebars_path: Path | None = None
        self._entries: list[DocEntry] = []
        self._dirs: list[DirEntry] = []

    # ------------------------------------------------------------------ load
    def load(self) -> "DocusaurusProject":
        if not self.root.is_dir():
            raise ProjectError(f"目录不存在：{self.root}")
        for name in CONFIG_NAMES:
            candidate = self.root / name
            if candidate.is_file():
                self.config_path = candidate
                break
        if self.config_path is None:
            raise ProjectError(
                f"没有找到 docusaurus.config.js/ts：{self.root}"
            )
        config_text = read_text(self.config_path)
        docs_rel = "docs"
        match = _DOCS_PATH_RE.search(config_text)
        if match:
            docs_rel = match.group(1).strip("/ ")
        self.docs_dir = (self.root / docs_rel).resolve()
        sidebars_match = _SIDEBARS_PATH_RE.search(config_text)
        sidebars_rel = sidebars_match.group(1) if sidebars_match else "sidebars.js"
        candidate = (self.root / sidebars_rel).resolve()
        self.sidebars_path = candidate if candidate.is_file() else None
        if self.sidebars_path is None:
            for name in ("sidebars.js", "sidebars.ts", "sidebars.json"):
                candidate = self.root / name
                if candidate.is_file():
                    self.sidebars_path = candidate
                    break
        self.scan()
        return self

    # ----------------------------------------------------------------- scan
    def scan(self) -> list[DocEntry]:
        if self.docs_dir is None:
            raise ProjectError("项目尚未加载")
        entries: list[DocEntry] = []
        directories: list[DirEntry] = []
        if self.docs_dir.is_dir():
            for path in sorted(self.docs_dir.rglob("*"), key=lambda p: natural_key(str(p))):
                if path.is_dir():
                    rel = relative_posix(path, self.docs_dir)
                    if not rel or any(
                        part.startswith((".", "_")) for part in Path(rel).parts
                    ):
                        continue
                    directories.append(self._read_dir(path))
                    continue
                if not path.is_file() or path.suffix.lower() not in DOC_SUFFIXES:
                    continue
                if path.name.startswith((".", "_")):
                    continue
                entries.append(self._read_entry(path))
        entries.sort(key=DocEntry.sort_key)
        self._entries = entries
        self._dirs = directories
        return entries

    def _read_dir(self, path: Path) -> DirEntry:
        assert self.docs_dir is not None
        data = self._category_data(path)
        position = data.get("position")
        if isinstance(position, str):
            try:
                position = int(position)
            except ValueError:
                position = None
        if not isinstance(position, int):
            position = None
        label = data.get("label")
        if not isinstance(label, str) or not label.strip():
            label = path.name
        link = data.get("link")
        return DirEntry(
            path=path,
            rel=relative_posix(path, self.docs_dir),
            label=label.strip(),
            position=position,
            link=link if isinstance(link, dict) else None,
            has_category=(path / "_category_.json").is_file(),
        )

    def _read_entry(self, path: Path) -> DocEntry:
        assert self.docs_dir is not None
        text = read_text(path)
        parsed = frontmatter.split(text)
        title = self._derive_title(parsed, path)
        position = parsed.values.get("sidebar_position")
        if isinstance(position, str):
            try:
                position = int(position)
            except ValueError:
                position = None
        if not isinstance(position, int):
            position = None
        doc_id = parsed.values.get("id")
        return DocEntry(
            path=path,
            rel=relative_posix(path, self.docs_dir),
            title=title,
            position=position,
            doc_id=str(doc_id) if doc_id is not None else None,
            front_matter=parsed,
            body=parsed.body,
        )

    @staticmethod
    def _derive_title(parsed: frontmatter.FrontMatter, path: Path) -> str:
        raw_title = parsed.values.get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            return raw_title.strip()
        for line in parsed.body.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip() or path.stem
            if stripped:
                break
        return path.stem

    # -------------------------------------------------------------- queries
    @property
    def entries(self) -> list[DocEntry]:
        return list(self._entries)

    @property
    def name(self) -> str:
        return self.root.name

    def exists(self) -> bool:
        return self.config_path is not None and self.config_path.is_file()

    @staticmethod
    def _parent_rel(rel: str) -> str:
        parent = Path(rel).parent.as_posix()
        return "" if parent in ("", ".") else parent

    def _direct_nodes(self, parent_rel: str) -> list[TreeNode]:
        """Documents and folders directly inside *parent_rel*, in sidebar order."""
        parent_rel = parent_rel.strip("/")
        docs = [
            entry for entry in self._entries if self._rel_dir(entry) == parent_rel
        ]
        dirs = [
            directory
            for directory in self._dirs
            if self._parent_rel(directory.rel) == parent_rel
        ]
        nodes = [
            TreeNode("doc", entry.rel, entry.title, entry.position, entry=entry)
            for entry in docs
        ]
        for directory in dirs:
            index_entry = next(
                (
                    entry
                    for entry in self._entries
                    if self._rel_dir(entry) == directory.rel
                    and entry.path.stem.lower() == "index"
                ),
                None,
            )
            position = directory.position
            label = directory.label
            if index_entry is not None:
                if position is None:
                    position = index_entry.position
                if (not directory.has_category) or label == Path(directory.rel).name:
                    label = index_entry.title
            nodes.append(
                TreeNode(
                    "dir",
                    directory.rel,
                    label,
                    position,
                    entry=index_entry,
                    directory=directory,
                    container=index_entry is not None,
                    index_rel=index_entry.rel if index_entry is not None else None,
                )
            )
        nodes.sort(
            key=lambda node: (
                node.position is None,
                node.position if node.position is not None else 0,
                natural_key(node.label),
            )
        )
        return nodes

    def sidebar_tree(self) -> list[TreeNode]:
        def build(parent_rel: str) -> list[TreeNode]:
            nodes = self._direct_nodes(parent_rel)
            for node in nodes:
                if node.kind == "dir":
                    children = build(node.rel)
                    if node.index_rel is not None:
                        children = [
                            child for child in children if child.rel != node.index_rel
                        ]
                    node.children = children
            return nodes

        return build("")

    def next_position(self, parent_rel: str = "") -> int:
        positions = [
            node.position
            for node in self._direct_nodes(parent_rel)
            if node.position is not None
        ]
        return (max(positions) + 1) if positions else 1

    def max_position(self) -> int:
        positions = [entry.position for entry in self._entries if entry.position is not None]
        positions += [
            directory.position
            for directory in self._dirs
            if directory.position is not None
        ]
        return max(positions) if positions else 0

    def find(self, path: Path | str) -> DocEntry | None:
        target = Path(path).resolve()
        for entry in self._entries:
            if entry.path.resolve() == target:
                return entry
        return None

    def doc_directories(self) -> list[Path]:
        assert self.docs_dir is not None
        dirs = [self.docs_dir]
        for path in sorted(self.docs_dir.rglob("*"), key=lambda p: natural_key(str(p))):
            if path.is_dir() and not path.name.startswith("."):
                dirs.append(path)
        return dirs

    # --------------------------------------------------------------- writes
    def create_doc(
        self,
        name: str,
        body: str = "",
        *,
        title: str | None = None,
        rel_dir: str = "",
        position: int | None = None,
        doc_id: str | None = None,
        extra: dict[str, object] | None = None,
        overwrite: bool = False,
    ) -> DocEntry:
        if self.docs_dir is None:
            raise ProjectError("项目尚未加载")
        suffix = Path(name).suffix.lower()
        if suffix not in DOC_SUFFIXES:
            suffix = ".mdx"
        stem = Path(name).stem if Path(name).suffix.lower() in DOC_SUFFIXES else name
        stem = slugify(stem, fallback="untitled")
        directory = (self.docs_dir / rel_dir).resolve() if rel_dir else self.docs_dir
        if self.docs_dir not in directory.parents and directory != self.docs_dir:
            raise ProjectError("目标目录不在 docs 目录内")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{stem}{suffix}"
        if path.exists() and not overwrite:
            path = unique_path(directory, stem, suffix)
        header = {
            "title": title if title else stem.replace("-", " "),
            "sidebar_position": position if position is not None else self.next_position(rel_dir),
        }
        if doc_id:
            header["id"] = doc_id
        if extra:
            header.update(extra)
        document = frontmatter.FrontMatter()
        text = document.with_overrides(header)
        if body:
            text = text.rstrip("\n") + "\n\n" + body.lstrip("\n")
        write_text(path, text if text.endswith("\n") else text + "\n")
        return self._read_and_register(path)

    def save_doc(
        self,
        entry: DocEntry,
        body: str,
        overrides: dict[str, object] | None = None,
    ) -> DocEntry:
        parsed = frontmatter.split(read_text(entry.path))
        parsed.body = body
        merged = dict(overrides or {})
        text = parsed.with_overrides(merged) if merged else frontmatter.join(parsed)
        text = text.rstrip("\n") + "\n"
        write_text(entry.path, text)
        return self._read_and_register(entry.path)

    def write_document(self, entry: DocEntry, text: str) -> DocEntry:
        """Write a fully rendered document (front matter + body) back."""
        write_text(entry.path, text if text.endswith("\n") else text + "\n")
        return self._read_and_register(entry.path)

    def delete_doc(self, entry: DocEntry) -> None:
        if not entry.path.exists():
            return
        entry.path.unlink()
        self._entries = [item for item in self._entries if item.path != entry.path]
        parent = entry.path.parent
        assert self.docs_dir is not None
        while parent != self.docs_dir and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    def rename_doc(self, entry: DocEntry, new_name: str) -> DocEntry:
        suffix = entry.path.suffix
        stem = new_name
        if Path(new_name).suffix.lower() in DOC_SUFFIXES:
            suffix = Path(new_name).suffix.lower()
            stem = Path(new_name).stem
        stem = slugify(stem, fallback=entry.path.stem)
        target = entry.path.with_name(f"{stem}{suffix}")
        if target == entry.path:
            return entry
        if target.exists():
            target = unique_path(entry.path.parent, stem, suffix)
        entry.path.rename(target)
        self._entries = [item for item in self._entries if item.path != entry.path]
        return self._read_and_register(target)

    @staticmethod
    def _rel_dir(entry: DocEntry) -> str:
        rel = Path(entry.rel).parent.as_posix()
        return "" if rel in ("", ".") else rel

    # ------------------------------------------------------- categories
    def _category_data(self, directory: Path) -> dict:
        path = directory / "_category_.json"
        if not path.is_file():
            return {}
        try:
            data = json.loads(read_text(path))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def set_dir_position(self, directory: DirEntry, position: int) -> None:
        path = directory.path / "_category_.json"
        data = self._category_data(directory.path)
        if not data:
            data = {"label": directory.label}
        if data.get("position") == position:
            return
        data["position"] = position
        write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    def _find_dir(self, rel: str) -> DirEntry | None:
        for directory in self._dirs:
            if directory.rel == rel:
                return directory
        return None

    def _container_index_rel(self, parent_rel: str) -> str | None:
        for entry in self._entries:
            if (
                self._rel_dir(entry) == parent_rel
                and entry.path.stem.lower() == "index"
            ):
                return entry.rel
        return None

    def _renumber(self, parent_rel: str) -> None:
        """Renumber documents and folders in one sidebar level to 1..n."""
        nodes = self._direct_nodes(parent_rel)
        for position, node in enumerate(nodes, start=1):
            if node.position == position:
                continue
            if node.kind == "doc":
                entry = next(
                    (item for item in self._entries if item.rel == node.rel), None
                )
                if entry is not None:
                    self.save_doc(entry, entry.body, {"sidebar_position": position})
            else:
                directory = self._find_dir(node.rel)
                if directory is not None:
                    self.set_dir_position(directory, position)
        self.scan()

    def _apply_order(self, parent_rel: str, ordered: list[TreeNode]) -> None:
        """Write an explicit order into documents and folder positions."""
        for position, node in enumerate(ordered, start=1):
            if node.kind == "doc":
                entry = next(
                    (item for item in self._entries if item.rel == node.rel), None
                )
                if entry is not None:
                    self.save_doc(entry, entry.body, {"sidebar_position": position})
            else:
                directory = self._find_dir(node.rel)
                if directory is not None:
                    self.set_dir_position(directory, position)
        self.scan()

    def _update_category_link(
        self, parent_rel: str, old_id: str, new_id: str
    ) -> None:
        """Point a folder's category link at the moved index document."""
        if self.docs_dir is None:
            return
        directory = self.docs_dir / parent_rel if parent_rel else self.docs_dir
        category = directory / "_category_.json"
        if not category.is_file():
            return
        data = self._category_data(directory)
        link = data.get("link")
        if (
            isinstance(link, dict)
            and link.get("type") == "doc"
            and link.get("id") == old_id
        ):
            link["id"] = new_id
            write_text(category, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    def _rewrite_category_links(
        self, root: Path, old_prefix: str, new_prefix: str
    ) -> None:
        """Keep _category_.json doc links valid after a folder moves."""
        for category in root.rglob("_category_.json"):
            data = self._category_data(category.parent)
            link = data.get("link")
            if not isinstance(link, dict) or link.get("type") != "doc":
                continue
            doc_id = link.get("id")
            if not isinstance(doc_id, str):
                continue
            if doc_id == old_prefix or doc_id.startswith(old_prefix + "/"):
                link["id"] = new_prefix + doc_id[len(old_prefix) :]
                write_text(
                    category, json.dumps(data, ensure_ascii=False, indent=2) + "\n"
                )

    def move_node(
        self, kind: str, rel: str, target_parent: str, index: int
    ) -> tuple[str, str]:
        """Move a document or a folder and renumber both affected levels."""
        if self.docs_dir is None:
            raise ProjectError("项目尚未加载")
        target_parent = target_parent.strip("/")
        if target_parent:
            target_path = (self.docs_dir / target_parent).resolve()
            if self.docs_dir not in target_path.parents:
                raise ProjectError("目标目录不在 docs 目录内")
        if kind == "doc":
            entry = next((item for item in self._entries if item.rel == rel), None)
            if entry is None:
                raise ProjectError(f"找不到文档：{rel}")
            source_path = entry.path
            source_parent = self._rel_dir(entry)
        elif kind == "dir":
            directory = self._find_dir(rel)
            if directory is None:
                raise ProjectError(f"找不到目录：{rel}")
            if target_parent == rel or target_parent.startswith(rel + "/"):
                raise ProjectError("不能把目录移动到它自己内部")
            source_path = directory.path
            source_parent = self._parent_rel(directory.rel)
        else:
            raise ProjectError(f"未知节点类型：{kind}")

        index_rel = self._container_index_rel(target_parent)
        offset = 1 if index_rel is not None else 0
        nodes = self._direct_nodes(target_parent)
        # ``index`` is the insertion position in the *visible* children list
        # after the source has been removed (the tree already compensates).
        visible_count = len(nodes) - offset
        if source_parent == target_parent:
            visible_count -= 1
        index = max(0, min(index, visible_count))
        model_index = index + offset

        new_path = source_path
        if source_parent != target_parent:
            destination_dir = (
                self.docs_dir / target_parent if target_parent else self.docs_dir
            )
            destination_dir.mkdir(parents=True, exist_ok=True)
            new_path = destination_dir / source_path.name
            if new_path.exists():
                if kind == "doc":
                    new_path = unique_path(
                        destination_dir, source_path.stem, source_path.suffix
                    )
                else:
                    new_path = unique_path(destination_dir, source_path.name, "")
            shutil.move(str(source_path), str(new_path))
            if kind == "dir":
                self._rewrite_category_links(
                    new_path,
                    rel,
                    relative_posix(new_path, self.docs_dir),
                )
            elif source_path.stem.lower() == "index":
                self._update_category_link(
                    source_parent,
                    relative_posix(source_path.with_suffix(""), self.docs_dir),
                    relative_posix(new_path.with_suffix(""), self.docs_dir),
                )

        new_rel = relative_posix(new_path, self.docs_dir)
        self.scan()
        target_nodes = self._direct_nodes(target_parent)
        source_node = next(
            (node for node in target_nodes if node.kind == kind and node.rel == new_rel),
            None,
        )
        if source_node is not None:
            ordered = [node for node in target_nodes if node is not source_node]
            model_index = max(0, min(model_index, len(ordered)))
            ordered.insert(model_index, source_node)
            if index_rel is not None:
                index_node = next(
                    (
                        node
                        for node in ordered
                        if node.kind == "doc" and node.rel == index_rel
                    ),
                    None,
                )
                if index_node is not None:
                    ordered.remove(index_node)
                    ordered.insert(0, index_node)
            self._apply_order(target_parent, ordered)
        if target_parent != source_parent:
            self._renumber(source_parent)
        self.scan()
        return kind, new_rel

    def ensure_container(self, entry: DocEntry) -> str:
        """Turn ``foo.md`` into ``foo/index.mdx`` + ``_category_.json``.

        The category links to the index document, while the index gets an
        absolute slug so its public URL stays ``/foo`` (a direct link).
        """
        if self.docs_dir is None:
            raise ProjectError("项目尚未加载")
        parent_rel = self._rel_dir(entry)
        if entry.path.stem.lower() == "index":
            if not parent_rel:
                raise ProjectError("docs 根目录的 index 文档不能作为容器")
            return parent_rel
        container_rel = Path(entry.rel).with_suffix("").as_posix()
        container_path = self.docs_dir / container_rel
        if container_path.exists() and not container_path.is_dir():
            raise ProjectError(f"已存在同名文件：{container_rel}")
        container_path.mkdir(parents=True, exist_ok=True)
        target = container_path / "index.mdx"
        if target.exists():
            raise ProjectError(f"{container_rel}/index.mdx 已存在")
        original = frontmatter.split(read_text(entry.path))
        overrides: dict[str, object] = {"sidebar_position": 1}
        if not original.values.get("slug"):
            overrides["slug"] = "/" + container_rel
        text = original.with_overrides(overrides)
        write_text(target, text if text.endswith("\n") else text + "\n")
        entry.path.unlink()

        category_path = container_path / "_category_.json"
        if not category_path.exists():
            doc_id = f"{container_rel}/index"
            original_id = original.values.get("id")
            if original_id:
                doc_id = f"{container_rel}/{original_id}"
            position = (
                entry.position
                if entry.position is not None
                else self.next_position(parent_rel)
            )
            data = {
                "label": entry.title,
                "position": position,
                "link": {"type": "doc", "id": doc_id},
            }
            write_text(
                category_path,
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            )
        self.scan()
        self._renumber(parent_rel)
        self.scan()
        return container_rel

    def move_document(self, entry: DocEntry, target_dir: str, index: int) -> DocEntry:
        """Move a document to *target_dir* at *index* and renumber positions."""
        _, rel = self.move_node("doc", entry.rel, target_dir, index)
        if self.docs_dir is None:
            return entry
        return self.find(self.docs_dir / rel) or entry

    def set_position(self, entry: DocEntry, position: int | None) -> DocEntry:
        return self.save_doc(entry, entry.body, {"sidebar_position": position})

    def move(self, entry: DocEntry, delta: int) -> DocEntry:
        """Move a document one slot up/down inside its own sidebar level."""
        parent = self._rel_dir(entry)
        index_rel = self._container_index_rel(parent)
        nodes = [
            node
            for node in self._direct_nodes(parent)
            if not (node.kind == "doc" and node.rel == index_rel)
        ]
        index = next(
            (i for i, node in enumerate(nodes) if node.kind == "doc" and node.rel == entry.rel),
            None,
        )
        if index is None:
            return entry
        target = index + delta
        if target < 0 or target >= len(nodes):
            return entry
        self.move_node("doc", entry.rel, parent, target)
        refreshed = self.find(entry.path)
        return refreshed or entry

    def _read_and_register(self, path: Path) -> DocEntry:
        entry = self._read_entry(path)
        self._entries = [item for item in self._entries if item.path != path]
        self._entries.append(entry)
        self._entries.sort(key=DocEntry.sort_key)
        return entry

    # ------------------------------------------------------------- scaffold
    def config_summary(self) -> dict[str, str]:
        from .config_editor import read_site_config

        if self.config_path is None:
            return {}
        return read_site_config(self.config_path)


def scaffold_project(root: str | Path, title: str = "My Docs") -> DocusaurusProject:
    """Create a minimal, runnable Docusaurus site skeleton."""
    root_path = Path(root).expanduser().resolve()
    for name in CONFIG_NAMES:
        if (root_path / name).exists():
            raise ProjectError(f"该目录已经是 Docusaurus 项目：{root_path}")
    root_path.mkdir(parents=True, exist_ok=True)
    (root_path / "docs").mkdir(exist_ok=True)
    (root_path / "src" / "css").mkdir(parents=True, exist_ok=True)
    (root_path / "static" / "img").mkdir(parents=True, exist_ok=True)

    write_text(
        root_path / "package.json",
        """{
  "name": "docueditor-site",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "start": "docusaurus start",
    "build": "docusaurus build",
    "deploy": "docusaurus deploy"
  },
  "dependencies": {
    "@docusaurus/core": "^3.5.0",
    "@docusaurus/preset-classic": "^3.5.0",
    "react": "^18.0.0",
    "react-dom": "^18.0.0"
  }
}
""",
    )
    write_text(
        root_path / "docusaurus.config.js",
        f"""// @ts-check
const {{ themes: {{ github }} }} = require('prism-react-renderer');

/** @type {{import('@docusaurus/types').Config}} */
const config = {{
  title: '{title}',
  tagline: 'Written with Docueditor',
  url: 'https://example.com',
  baseUrl: '/',
  onBrokenLinks: 'warn',
  onBrokenMarkdownLinks: 'warn',
  favicon: 'img/favicon.ico',
  organizationName: 'avis-illusio',
  projectName: 'docueditor-site',

  presets: [
    [
      'classic',
      /** @type {{import('@docusaurus/preset-classic').Options}} */
      ({{
        docs: {{
          sidebarPath: require.resolve('./sidebars.js'),
          editUrl: undefined,
        }},
        blog: false,
        theme: {{
          customCss: require.resolve('./src/css/custom.css'),
        }},
      }}),
    ],
  ],

  themeConfig:
    /** @type {{import('@docusaurus/preset-classic').ThemeConfig}} */
    ({{
      navbar: {{
        title: '{title}',
        items: [
          {{ type: 'docSidebar', sidebarId: 'docs', position: 'left', label: '文档' }},
        ],
      }},
      footer: {{
        style: 'dark',
        copyright: `Copyright © ${{new Date().getFullYear()}} {title}`,
      }},
    }}),
}};

module.exports = config;
""",
    )
    write_text(
        root_path / "sidebars.js",
        """/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docs: [{ type: 'autogenerated', dirName: '.' }],
};

module.exports = sidebars;
""",
    )
    write_text(
        root_path / "src" / "css" / "custom.css",
        ":root {\n  --ifm-color-primary: #2e8555;\n}\n",
    )
    write_text(
        root_path / "docs" / "intro.mdx",
        """---
title: 开始使用
sidebar_position: 1
---

# 开始使用

这是由 Docueditor 创建的 Docusaurus 文档站。

## 下一步

- 在左侧新建文档
- 用工具栏编辑富文本
- 从 `文件 → 导入` 迁移 Novelwriter 或语雀内容
""",
    )
    write_text(
        root_path / "static" / "img" / "logo.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="12" fill="#2e8555"/>'
        '<path d="M18 18h20l8 8v20H18z" fill="#fff"/>'
        "</svg>\n",
    )
    return DocusaurusProject(root_path).load()
