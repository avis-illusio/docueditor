"""The Docusaurus project model.

Everything that touches the file system lives here so the GUI stays thin and
the behaviour can be unit tested without a display server.
"""

from __future__ import annotations

import re
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


class DocusaurusProject:
    """A folder containing a Docusaurus site."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.config_path: Path | None = None
        self.docs_dir: Path | None = None
        self.sidebars_path: Path | None = None
        self._entries: list[DocEntry] = []

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
        if self.docs_dir.is_dir():
            for path in sorted(self.docs_dir.rglob("*"), key=lambda p: natural_key(str(p))):
                if not path.is_file() or path.suffix.lower() not in DOC_SUFFIXES:
                    continue
                entries.append(self._read_entry(path))
        entries.sort(key=DocEntry.sort_key)
        self._entries = entries
        return entries

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

    def next_position(self) -> int:
        positions = [entry.position for entry in self._entries if entry.position is not None]
        return (max(positions) + 1) if positions else 1

    def max_position(self) -> int:
        positions = [entry.position for entry in self._entries if entry.position is not None]
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
            suffix = ".md"
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
            "sidebar_position": position if position is not None else self.next_position(),
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

    def set_position(self, entry: DocEntry, position: int | None) -> DocEntry:
        return self.save_doc(entry, entry.body, {"sidebar_position": position})

    def move(self, entry: DocEntry, delta: int) -> DocEntry:
        """Move a document one slot up/down by swapping sidebar positions."""
        ordered = sorted(self._entries, key=DocEntry.sort_key)
        try:
            index = ordered.index(entry)
        except ValueError:
            return entry
        target_index = index + delta
        if target_index < 0 or target_index >= len(ordered):
            return entry
        other = ordered[target_index]
        if entry.position is None:
            entry = self.set_position(entry, self.next_position())
            ordered = sorted(self._entries, key=DocEntry.sort_key)
            index = ordered.index(entry)
            target_index = index + delta
            if target_index < 0 or target_index >= len(ordered):
                return entry
            other = ordered[target_index]
        if other.position is None:
            other = self.set_position(other, self.next_position())
        first_pos = entry.position
        second_pos = other.position
        entry = self.set_position(entry, second_pos)
        other = self.set_position(other, first_pos)
        self.scan()
        return self.find(entry.path) or entry

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
        root_path / "docs" / "intro.md",
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
