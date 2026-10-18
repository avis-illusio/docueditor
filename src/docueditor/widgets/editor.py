"""The rich-text Markdown editor widget.

The WYSIWYG view is a ``QTextEdit`` driven by Qt's Markdown document model.
Constructs that Qt cannot represent (fenced code with a language tag, MDX
imports, JSX, admonitions) are replaced by tokens and restored on save, so
saving never destroys them.  A plain-source view is available for direct
editing.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, Qt, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QKeySequence,
    QShortcut,
    QTextBlock,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrameFormat,
    QTextImageFormat,
    QTextLength,
    QTextListFormat,
    QTextTable,
    QTextTableFormat,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import frontmatter, mdx_guard
from ..utils import word_count

TABLE_ALIGN_PROPERTY = int(QTextFormat.Property.UserProperty) + 1

GITHUB_DIALECT = getattr(
    QTextDocument,
    "MarkdownDialectGitHub",
    getattr(getattr(QTextDocument, "MarkdownFeature", object), "MarkdownDialectGitHub", 0),
)


def _feature_markdown() -> int:
    return GITHUB_DIALECT


class MarkdownTextEdit(QTextEdit):
    """QTextEdit that routes pasted/dropped images through a handler."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.image_handler = None

    @staticmethod
    def _image_urls(source: QMimeData) -> list[QUrl]:
        suffixes = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
        if not source.hasUrls():
            return []
        return [
            url
            for url in source.urls()
            if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in suffixes
        ]

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802
        if self.image_handler is not None and (
            source.hasImage() or self._image_urls(source)
        ):
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        if self.image_handler is not None:
            path = self.image_handler(source)
            if path:
                image_format = QTextImageFormat()
                image_format.setName(path)
                image_format.setProperty(
                    QTextFormat.Property.ImageAltText, "image"
                )
                self.textCursor().insertImage(image_format)
                return
        super().insertFromMimeData(source)


class MarkdownEditor(QWidget):
    """WYSIWYG + source editor for one Markdown/MDX file."""

    modifiedChanged = Signal(bool)
    wordCountChanged = Signal(int)
    cursorPositionChanged = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path: Path | None = None
        self._source_mode = False
        self._loading = False
        self._front_matter = frontmatter.FrontMatter()
        self._protected = mdx_guard.Protected("")
        self._pending_overrides: dict[str, object] = {}
        self._injected_title = False
        self._injected_title_text = ""
        self._editing_hr_pos: int | None = None
        self._suppress_hr_finish = False
        self._parsed_table_alignments: list[list[str]] = []
        self._docs_dir: Path | None = None
        self._document_dir: Path | None = None

        self.text_edit = MarkdownTextEdit()
        self.text_edit.setAcceptRichText(True)
        self.text_edit.setPlaceholderText("在这里开始书写……")
        self.text_edit.setTabChangesFocus(False)
        self.text_edit.image_handler = self._handle_image_mime
        document = self.text_edit.document()
        document.setDefaultFont(QFont("Noto Sans CJK SC", 11))

        self.source_edit = QPlainTextEdit()
        self.source_edit.setPlaceholderText("Markdown 源码")
        self.source_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        font = QFont("JetBrains Mono", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.source_edit.setFont(font)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.text_edit)
        self.stack.addWidget(self.source_edit)

        self.toolbar = self._build_toolbar()
        self.table_bar = self._build_table_bar()
        self.hint = QLabel("")
        self.hint.setObjectName("editorHint")
        self.hint.setWordWrap(True)
        self.hint.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.table_bar)
        layout.addWidget(self.hint)
        layout.addWidget(self.stack, 1)

        self.text_edit.installEventFilter(self)
        self.text_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.text_edit.customContextMenuRequested.connect(self._show_editor_menu)
        self.text_edit.textChanged.connect(self._on_changed)
        self.source_edit.textChanged.connect(self._on_changed)
        self.text_edit.document().modificationChanged.connect(self._emit_modified)
        self.source_edit.document().modificationChanged.connect(self._emit_modified)
        self.text_edit.cursorPositionChanged.connect(self._emit_cursor)
        self.text_edit.cursorPositionChanged.connect(self._maybe_finish_hr_edit)
        self.text_edit.cursorPositionChanged.connect(self._update_table_bar)
        self.source_edit.cursorPositionChanged.connect(self._emit_cursor)
        self._install_shortcuts()

    # ------------------------------------------------------------- toolbar
    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("editorToolbar")
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(2)

        first = QHBoxLayout()
        first.setSpacing(4)
        self.heading_combo = QComboBox()
        self.heading_combo.addItems(["正文", "标题 1", "标题 2", "标题 3"])
        self.heading_combo.setFixedWidth(96)
        self.heading_combo.currentIndexChanged.connect(self._apply_heading)
        first.addWidget(self.heading_combo)

        for label, tooltip, slot in (
            ("B", "粗体 (Ctrl+B)", self._toggle_weight),
            ("I", "斜体 (Ctrl+I)", self._toggle_italic),
            ("S", "删除线 (Ctrl+Shift+X)", self._toggle_strike),
            ("<>", "行内代码 (Ctrl+`)", self._toggle_code),
            ("• 列表", "无序列表", lambda: self._make_list(QTextListFormat.Style.ListDisc)),
            ("1. 列表", "有序列表", lambda: self._make_list(QTextListFormat.Style.ListDecimal)),
            ("任务", "任务列表", self._insert_task_list),
            ("引用", "引用块 (Ctrl+Shift+Q)", self._toggle_quote),
            ("链接", "插入链接 (Ctrl+K)", self._insert_link),
            ("清除格式", "清除格式", self._clear_format),
        ):
            button = QToolButton()
            button.setText(label)
            button.setToolTip(tooltip)
            button.setAutoRaise(True)
            button.clicked.connect(slot)
            first.addWidget(button)
        first.addStretch(1)

        second = QHBoxLayout()
        second.setSpacing(4)
        for label, tooltip, slot in (
            ("代码块", "代码块（可编辑，语言可后续在源码模式调整）", self._toggle_block_code),
            ("表格", "插入 Markdown 表格", self._insert_table),
            ("图片", "插入图片", self._insert_image),
            ("分隔线", "插入水平分隔线", self._insert_hr),
        ):
            button = QToolButton()
            button.setText(label)
            button.setToolTip(tooltip)
            button.setAutoRaise(True)
            button.clicked.connect(slot)
            second.addWidget(button)
        second.addStretch(1)
        self.mode_button = QPushButton("源码模式")
        self.mode_button.setCheckable(True)
        self.mode_button.setToolTip("在富文本与 Markdown 源码之间切换 (Ctrl+E)")
        self.mode_button.toggled.connect(self.set_source_mode)
        second.addWidget(self.mode_button)

        outer.addLayout(first)
        outer.addLayout(second)
        return bar

    def _build_table_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("tableToolbar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 3, 8, 3)
        row.setSpacing(4)
        for label, tooltip, slot in (
            ("上方行", "在上方插入行", lambda: self._table_insert_row(0)),
            ("下方行", "在下方插入行", lambda: self._table_insert_row(1)),
            ("删行", "删除当前行", self._table_delete_row),
            ("左列", "在左侧插入列", lambda: self._table_insert_column(0)),
            ("右列", "在右侧插入列", lambda: self._table_insert_column(1)),
            ("删列", "删除当前列", self._table_delete_column),
            ("左对齐", "当前列左对齐", lambda: self._table_set_alignment("left")),
            ("居中", "当前列居中对齐", lambda: self._table_set_alignment("center")),
            ("右对齐", "当前列右对齐", lambda: self._table_set_alignment("right")),
            ("删表", "删除表格", self._table_delete),
        ):
            button = QToolButton()
            button.setText(label)
            button.setToolTip(tooltip)
            button.setAutoRaise(True)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        bar.hide()
        return bar

    def _update_table_bar(self) -> None:
        if not hasattr(self, "table_bar"):
            return
        visible = (
            not self._source_mode
            and self.text_edit.textCursor().currentTable() is not None
        )
        self.table_bar.setVisible(visible)

    def _install_shortcuts(self) -> None:
        for sequence, slot in (
            ("Ctrl+B", self._toggle_weight),
            ("Ctrl+I", self._toggle_italic),
            ("Ctrl+Shift+X", self._toggle_strike),
            ("Ctrl+`", self._toggle_code),
            ("Ctrl+K", self._insert_link),
            ("Ctrl+Shift+Q", self._toggle_quote),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

    # -------------------------------------------------------------- loading
    def load_document(self, path: Path, text: str) -> None:
        self._loading = True
        self._path = path
        self._document_dir = path.parent
        self._pending_overrides = {}
        self._editing_hr_pos = None
        self._front_matter = frontmatter.split(text)
        self._parsed_table_alignments = self._parse_table_alignments(self._front_matter.body)
        body = self._prepare_body(self._front_matter)
        self._protected = mdx_guard.protect(body)
        self.text_edit.document().setMarkdown(self._protected.text, _feature_markdown())
        self._apply_typography()
        self._apply_table_alignments()
        self.source_edit.setPlainText(text if text.endswith("\n") else text + "\n")
        self.text_edit.document().setModified(False)
        self.source_edit.document().setModified(False)
        self.heading_combo.setCurrentIndex(0)
        self._loading = False
        self._update_hint()
        self._emit_modified(False)
        self._emit_word_count()

    def clear_document(self) -> None:
        self._loading = True
        self._path = None
        self._front_matter = frontmatter.FrontMatter()
        self._protected = mdx_guard.Protected("")
        self._injected_title = False
        self._injected_title_text = ""
        self._editing_hr_pos: int | None = None
        self._suppress_hr_finish = False
        self._parsed_table_alignments: list[list[str]] = []
        self._document_dir: Path | None = None
        self.text_edit.clear()
        self.source_edit.clear()
        self.text_edit.document().setModified(False)
        self.source_edit.document().setModified(False)
        self._loading = False
        self.hint.hide()
        self._emit_word_count()

    def _update_hint(self) -> None:
        labels = mdx_guard.describe_tokens(self._protected)
        if not labels:
            self.hint.hide()
            return
        self.hint.setText(
            "已保护 " + str(len(labels)) + " 个 MDX 结构（保存时原样写回）：" + "；".join(labels[:4])
            + ("…" if len(labels) > 4 else "")
        )
        self.hint.show()

    # ------------------------------------------------------------- document
    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def source_mode(self) -> bool:
        return self._source_mode

    def set_project_context(self, docs_dir: Path | None) -> None:
        self._docs_dir = Path(docs_dir) if docs_dir is not None else None

    def _unique_asset_path(self, suffix: str) -> Path:
        assert self._docs_dir is not None
        assets = self._docs_dir / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = assets / f"image-{stamp}{suffix}"
        counter = 2
        while candidate.exists():
            candidate = assets / f"image-{stamp}-{counter}{suffix}"
            counter += 1
        return candidate

    def _handle_image_mime(self, source: QMimeData) -> str | None:
        if self._docs_dir is None:
            return None
        target: Path | None = None
        if source.hasImage():
            image = QImage(source.imageData())
            if image.isNull():
                return None
            target = self._unique_asset_path(".png")
            if not image.save(str(target), "PNG"):
                return None
        else:
            urls = MarkdownTextEdit._image_urls(source)
            if not urls:
                return None
            source_path = Path(urls[0].toLocalFile())
            suffix = source_path.suffix.lower() or ".png"
            target = self._unique_asset_path(suffix)
            try:
                shutil.copy2(source_path, target)
            except OSError:
                return None
        base = self._document_dir or self._docs_dir
        try:
            relative = os.path.relpath(target, base).replace(os.sep, "/")
        except ValueError:
            relative = target.as_posix()
        return relative

    def current_text(self) -> str:
        if self._source_mode:
            return self.source_edit.toPlainText()
        self._finish_hr_edit()
        markdown = self.text_edit.document().toMarkdown(_feature_markdown())
        restored = mdx_guard.restore(markdown, self._protected)
        restored = self._replace_tables(restored)
        restored = self._normalize_horizontal_rules(restored)
        overrides = dict(self._pending_overrides)
        if self._injected_title:
            match = re.match(r"^#\s+(.+?)\s*\n+", restored)
            if match:
                heading = match.group(1).strip()
                restored = "\n" + restored[match.end() :].lstrip("\n")
                if "title" not in overrides and heading:
                    overrides["title"] = heading
        header = list(self._front_matter.lines)
        merged = frontmatter.FrontMatter(
            lines=header,
            body=restored,
            has_header=self._front_matter.has_header or bool(header),
        )
        text = merged.with_overrides(overrides) if overrides else frontmatter.join(merged)
        return text if text.endswith("\n") else text + "\n"

    # -------------------------------------------------------------- tables
    def _collect_tables(self) -> list[QTextTable]:
        tables: list[QTextTable] = []
        root = self.text_edit.document().rootFrame()

        def walk(frame) -> None:
            iterator = frame.begin()
            while not iterator.atEnd():
                child = iterator.currentFrame()
                if isinstance(child, QTextTable):
                    tables.append(child)
                elif child is not None:
                    walk(child)
                iterator += 1

        walk(root)
        return tables

    @staticmethod
    def _cell_text(table: QTextTable, row: int, column: int) -> str:
        cell = table.cellAt(row, column)
        cursor = QTextCursor(cell.firstCursorPosition())
        cursor.setPosition(
            cell.lastCursorPosition().position(), QTextCursor.MoveMode.KeepAnchor
        )
        text = cursor.selectedText()
        text = text.replace("\u2029", "<br>").replace("\n", "<br>")
        text = re.sub(r"^(?:<br>)+|(?:<br>)+$", "", text).strip()
        text = re.sub(r"(?:<br>){2,}", "<br>", text)
        return text.replace("|", "\\|")

    def _table_to_markdown(self, table: QTextTable) -> str:
        rows = table.rows()
        columns = table.columns()
        if rows <= 0 or columns <= 0:
            return ""
        data = [
            [self._cell_text(table, row, column) for column in range(columns)]
            for row in range(rows)
        ]
        alignments = self._table_alignments(table)
        separator = {
            "left": "---",
            "center": ":---:",
            "right": "---:",
        }
        lines = [
            "| " + " | ".join(data[0]) + " |",
            "| "
            + " | ".join(
                separator.get(alignments[column], "---")
                for column in range(columns)
            )
            + " |",
        ]
        for row in data[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)

    def _replace_tables(self, markdown: str) -> str:
        tables = self._collect_tables()
        if not tables:
            return markdown
        lines = markdown.splitlines(keepends=True)
        blocks: list[tuple[int, int]] = []
        in_fence = False
        fence = ""
        index = 0
        row_re = re.compile(r"^[ \t]*\|.*\|[ \t]*$")
        while index < len(lines):
            stripped = lines[index].strip()
            if stripped.startswith(("```", "~~~")):
                marker = stripped[:3]
                if not in_fence:
                    in_fence = True
                    fence = marker
                elif stripped.startswith(fence):
                    in_fence = False
                index += 1
                continue
            if not in_fence and row_re.match(lines[index].rstrip("\n")):
                begin = index
                while index < len(lines) and row_re.match(
                    lines[index].rstrip("\n")
                ):
                    index += 1
                blocks.append((begin, index))
            else:
                index += 1
        for (begin, end), table in reversed(list(zip(blocks, tables))):
            replacement = self._table_to_markdown(table) + "\n"
            lines[begin:end] = [replacement]
        return "".join(lines)

    @staticmethod
    def _normalize_horizontal_rules(markdown: str) -> str:
        lines = markdown.splitlines(keepends=True)
        in_fence = False
        fence = ""
        hr_re = re.compile(r"^[-*_](?:\s+[-*_]){2,}\s*$")
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                marker = stripped[:3]
                if not in_fence:
                    in_fence = True
                    fence = marker
                elif stripped.startswith(fence):
                    in_fence = False
                continue
            if in_fence:
                continue
            if hr_re.match(stripped) or stripped.replace("\\", "") in {
                "---",
                "***",
                "___",
            }:
                lines[index] = "---\n" if line.endswith("\n") else "---"
        return "".join(lines)

    def _prepare_body(self, parsed: frontmatter.FrontMatter) -> str:
        """Inject front matter ``title`` as a visible H1 in the WYSIWYG view."""
        title = parsed.values.get("title")
        body = parsed.body
        self._injected_title = False
        self._injected_title_text = ""
        if isinstance(title, str) and title.strip():
            first = next(
                (line.strip() for line in body.splitlines() if line.strip()), ""
            )
            if not first.startswith("# "):
                self._injected_title = True
                self._injected_title_text = title.strip()
                body = f"# {title.strip()}\n\n{body}"
        return body

    def set_front_matter_overrides(self, overrides: dict[str, object]) -> None:
        self._pending_overrides.update(overrides)

    def clear_front_matter_overrides(self) -> None:
        self._pending_overrides.clear()

    def title(self) -> str:
        value = self._pending_overrides.get("title", self._front_matter.values.get("title"))
        if isinstance(value, str) and value.strip():
            return value.strip()
        return self._path.stem if self._path else "未命名"

    def set_source_mode(self, enabled: bool) -> None:
        if enabled == self._source_mode:
            self.mode_button.setChecked(enabled)
            return
        if enabled and hasattr(self, "table_bar"):
            self.table_bar.hide()
        self._pending_overrides.clear()
        if enabled:
            text = self.current_text()
            self._loading = True
            self.source_edit.setPlainText(text)
            self.source_edit.document().setModified(False)
            self._loading = False
            self.stack.setCurrentWidget(self.source_edit)
        else:
            text = self.source_edit.toPlainText()
            self._loading = True
            self._front_matter = frontmatter.split(text)
            self._parsed_table_alignments = self._parse_table_alignments(
                self._front_matter.body
            )
            body = self._prepare_body(self._front_matter)
            self._protected = mdx_guard.protect(body)
            self.text_edit.document().setMarkdown(self._protected.text, _feature_markdown())
            self._apply_typography()
            self._apply_table_alignments()
            self.text_edit.document().setModified(False)
            self._loading = False
            self._update_hint()
            self.stack.setCurrentWidget(self.text_edit)
        self._source_mode = enabled
        self.mode_button.blockSignals(True)
        self.mode_button.setChecked(enabled)
        self.mode_button.setText("富文本模式" if enabled else "源码模式")
        self.mode_button.blockSignals(False)
        self.hint.setVisible(not enabled and bool(self._protected.tokens))
        self._update_table_bar()
        self._emit_word_count()

    def set_modified(self, value: bool) -> None:
        self.text_edit.document().setModified(value)
        self.source_edit.document().setModified(value)

    def is_modified(self) -> bool:
        if self._source_mode:
            return self.source_edit.document().isModified()
        return self.text_edit.document().isModified()

    # ---------------------------------------------------------------- slots
    def _on_changed(self) -> None:
        if self._loading:
            return
        self._emit_word_count()
        if self._source_mode:
            self.text_edit.document().setModified(True)
        else:
            self.source_edit.document().setModified(True)

    def _emit_modified(self, value: bool) -> None:
        self.modifiedChanged.emit(self.is_modified())

    def _emit_word_count(self) -> None:
        text = self.source_edit.toPlainText() if self._source_mode else self.text_edit.toPlainText()
        self.wordCountChanged.emit(word_count(text))

    def _emit_cursor(self) -> None:
        widget = self.source_edit if self._source_mode else self.text_edit
        cursor = widget.textCursor()
        self.cursorPositionChanged.emit(cursor.blockNumber() + 1, cursor.columnNumber() + 1)

    # ------------------------------------------------------------ formatting
    def _cursor(self) -> QTextCursor:
        return self.text_edit.textCursor()

    def _merge_char_format(self, fmt: QTextCharFormat) -> None:
        cursor = self._cursor()
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        else:
            self.text_edit.mergeCurrentCharFormat(fmt)
        self.text_edit.setFocus()

    def _toggle_weight(self) -> None:
        if self._source_mode:
            self._wrap_selection("**")
            return
        weight = self._cursor().charFormat().fontWeight()
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Normal if weight >= QFont.Weight.Bold else QFont.Weight.Bold)
        self._merge_char_format(fmt)

    def _toggle_italic(self) -> None:
        if self._source_mode:
            self._wrap_selection("*")
            return
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self._cursor().charFormat().fontItalic())
        self._merge_char_format(fmt)

    def _toggle_strike(self) -> None:
        if self._source_mode:
            self._wrap_selection("~~")
            return
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not self._cursor().charFormat().fontStrikeOut())
        self._merge_char_format(fmt)

    def _toggle_code(self) -> None:
        if self._source_mode:
            self._wrap_selection("`")
            return
        fmt = QTextCharFormat()
        current = self._cursor().charFormat()
        fixed = current.fontFixedPitch()
        fmt.setFontFixedPitch(not fixed)
        if fixed:
            fmt.setFontFamilies([])
        else:
            fmt.setFontFamilies(["JetBrains Mono", "monospace"])
        self._merge_char_format(fmt)

    def _wrap_selection(self, marker: str) -> None:
        cursor = self.source_edit.textCursor()
        selected = cursor.selectedText()
        cursor.insertText(f"{marker}{selected}{marker}")
        self.source_edit.setTextCursor(cursor)

    def _apply_heading(self, index: int) -> None:
        if self._source_mode or self._loading:
            return
        cursor = self._cursor()
        block_format = cursor.blockFormat()
        block_format.setHeadingLevel(index)
        cursor.setBlockFormat(block_format)
        self.text_edit.setFocus()

    def _make_list(self, style: QTextListFormat.Style) -> None:
        if self._source_mode:
            prefix = "1. " if style == QTextListFormat.Style.ListDecimal else "- "
            cursor = self.source_edit.textCursor()
            cursor.beginEditBlock()
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.insertText(prefix)
            cursor.endEditBlock()
            return
        cursor = self._cursor()
        current = cursor.currentList()
        if current is not None:
            current.remove(cursor.block())
            block_format = cursor.blockFormat()
            block_format.setIndent(0)
            cursor.setBlockFormat(block_format)
            return
        list_format = QTextListFormat()
        list_format.setStyle(style)
        list_format.setIndent(1)
        cursor.createList(list_format)
        self.text_edit.setFocus()

    def _insert_link(self) -> None:
        if self._source_mode:
            text, ok = QInputDialog.getText(self, "插入链接", "链接文字：")
            if not ok or not text:
                return
            url, ok = QInputDialog.getText(self, "插入链接", "URL：")
            if not ok or not url:
                return
            cursor = self.source_edit.textCursor()
            cursor.insertText(f"[{text}]({url})")
            return
        url, ok = QInputDialog.getText(self, "插入链接", "URL：")
        if not ok or not url.strip():
            return
        cursor = self._cursor()
        selected = cursor.selectedText()
        if not selected:
            label, ok = QInputDialog.getText(self, "插入链接", "链接文字：")
            if not ok:
                return
            selected = label or url
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(url.strip())
        fmt.setFontUnderline(True)
        fmt.setForeground(Qt.GlobalColor.blue)
        cursor.insertText(selected, fmt)
        self.text_edit.setFocus()

    # ------------------------------------------------------------ typography
    def _apply_typography(self) -> None:
        document = self.text_edit.document()
        document.setDefaultFont(QFont("Noto Sans CJK SC", 11))
        block = document.begin()
        while block.isValid():
            self._style_block(block)
            block = block.next()
        self._style_tables()
        try:
            document.clearUndoRedoStacks()
        except AttributeError:
            pass

    def _style_block(self, block: QTextBlock) -> None:
        fmt = block.blockFormat()
        heading = fmt.headingLevel()
        code = fmt.property(QTextFormat.Property.BlockCodeLanguage)
        quote = fmt.property(QTextFormat.Property.BlockQuoteLevel) or 0
        sizes = {1: 26.0, 2: 21.0, 3: 18.0, 4: 16.0, 5: 14.0, 6: 13.0}
        if heading:
            fmt.setTopMargin(26 if heading == 1 else 18)
            fmt.setBottomMargin(10)
            fmt.setLeftMargin(0)
            fmt.setRightMargin(0)
            fmt.setLineHeight(130, 1)
            size = sizes.get(heading, 13.0)
            color = QColor("#1f2328")
            weight = QFont.Weight.Bold
            families = ["Noto Sans CJK SC"]
        elif code:
            fmt.setBackground(QColor("#f6f8fa"))
            fmt.setLeftMargin(16)
            fmt.setRightMargin(16)
            fmt.setTopMargin(8)
            fmt.setBottomMargin(8)
            fmt.setLineHeight(145, 1)
            size = 10.5
            color = QColor("#24292f")
            weight = QFont.Weight.Normal
            families = ["JetBrains Mono", "Fira Code", "monospace"]
        elif quote:
            fmt.setBackground(QColor("#f6f8fa"))
            fmt.setLeftMargin(18)
            fmt.setRightMargin(14)
            fmt.setTopMargin(6)
            fmt.setBottomMargin(6)
            fmt.setLineHeight(165, 1)
            size = 11.5
            color = QColor("#57606a")
            weight = QFont.Weight.Normal
            families = ["Noto Sans CJK SC"]
        elif fmt.hasProperty(
            QTextFormat.Property.BlockTrailingHorizontalRulerWidth
        ) and fmt.property(QTextFormat.Property.BlockTrailingHorizontalRulerWidth):
            fmt.setLeftMargin(0)
            fmt.setRightMargin(0)
            fmt.setTopMargin(16)
            fmt.setBottomMargin(16)
            fmt.setLineHeight(100, 1)
            fmt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            size = 8.0
            color = QColor("#d0d7de")
            weight = QFont.Weight.Normal
            families = ["Noto Sans CJK SC"]
        else:
            fmt.clearBackground()
            fmt.setLeftMargin(0)
            fmt.setRightMargin(0)
            fmt.setTopMargin(0)
            fmt.setBottomMargin(6)
            fmt.setLineHeight(170, 1)
            is_rule = block.text().strip() in {"---", "***", "___"}
            fmt.setAlignment(
                Qt.AlignmentFlag.AlignHCenter if is_rule else Qt.AlignmentFlag.AlignLeft
            )
            size = 11.5
            color = QColor("#9aa2ab") if is_rule else QColor("#24292f")
            weight = QFont.Weight.Normal
            families = ["Noto Sans CJK SC"]
        has_image = False
        probe = block.begin()
        while not probe.atEnd():
            fragment = probe.fragment()
            if fragment.isValid() and fragment.charFormat().isImageFormat():
                has_image = True
                break
            probe += 1
        if has_image:
            fmt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        cursor = QTextCursor(block)
        cursor.setBlockFormat(fmt)
        char = QTextCharFormat()
        char.setFontPointSize(size)
        char.setForeground(color)
        char.setFontWeight(weight)
        char.setFontFamilies(families)
        if code:
            char.setFontFixedPitch(True)
        content = QTextCursor(block)
        content.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        content.movePosition(
            QTextCursor.MoveOperation.EndOfBlock,
            QTextCursor.MoveMode.KeepAnchor,
        )
        content.mergeCharFormat(char)
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.charFormat().isAnchor():
                link_format = QTextCharFormat()
                link_format.setForeground(QColor("#2e8555"))
                link_format.setFontUnderline(False)
                link_cursor = QTextCursor(self.text_edit.document())
                link_cursor.setPosition(fragment.position())
                link_cursor.setPosition(
                    fragment.position() + fragment.length(),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                link_cursor.mergeCharFormat(link_format)
            iterator += 1

    def _style_tables(self) -> None:
        for table in self._collect_tables():
            fmt = table.format()
            fmt.setBorder(1)
            fmt.setBorderBrush(QColor("#d0d7de"))
            fmt.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
            fmt.setCellPadding(8)
            fmt.setCellSpacing(0)
            fmt.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
            table.setFormat(fmt)
            for column in range(table.columns()):
                cell = table.cellAt(0, column)
                cell_format = cell.format()
                cell_format.setBackground(QColor("#f6f8fa"))
                cell_format.setFontWeight(QFont.Weight.Bold)
                cell.setFormat(cell_format)
            self._apply_cell_alignment(table, self._table_alignments(table))

    # --------------------------------------------------------- autoformat
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.text_edit and event.type() == QEvent.Type.MouseButtonDblClick:
            if self._begin_hr_edit(event.position().toPoint()):
                return True
        if obj is self.text_edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._autoformat_hr():
                    return True
            elif key == Qt.Key.Key_Space:
                if self._autoformat_prefix():
                    return True
        return super().eventFilter(obj, event)

    def _begin_hr_edit(self, point) -> bool:
        cursor = self.text_edit.cursorForPosition(point)
        block = cursor.block()
        fmt = block.blockFormat()
        if not (
            fmt.hasProperty(QTextFormat.Property.BlockTrailingHorizontalRulerWidth)
            and fmt.property(QTextFormat.Property.BlockTrailingHorizontalRulerWidth)
        ):
            return False
        self._finish_hr_edit()
        self._suppress_hr_finish = True
        cursor = QTextCursor(block)
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.insertText("---")
        new_format = cursor.blockFormat()
        new_format.clearProperty(
            QTextFormat.Property.BlockTrailingHorizontalRulerWidth
        )
        new_format.setAlignment(Qt.AlignmentFlag.AlignLeft)
        cursor.setBlockFormat(new_format)
        current_block = cursor.block()
        self._editing_hr_pos = current_block.position()
        start = current_block.position()
        cursor.setPosition(start)
        cursor.setPosition(
            start + len(current_block.text()), QTextCursor.MoveMode.KeepAnchor
        )
        cursor.endEditBlock()
        self.text_edit.setTextCursor(cursor)
        self._suppress_hr_finish = False
        return True

    def _finish_hr_edit(self) -> None:
        if self._editing_hr_pos is None:
            return
        self._suppress_hr_finish = True
        block = self.text_edit.document().findBlock(self._editing_hr_pos)
        self._editing_hr_pos = None
        if not block.isValid():
            return
        if block.text().strip() not in {"---", "***", "___"}:
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.removeSelectedText()
        fmt = cursor.blockFormat()
        fmt.setProperty(QTextFormat.Property.BlockTrailingHorizontalRulerWidth, 1)
        fmt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        cursor.setBlockFormat(fmt)
        self._style_block(block)
        self._suppress_hr_finish = False

    def _maybe_finish_hr_edit(self) -> None:
        if self._suppress_hr_finish or self._editing_hr_pos is None:
            return
        if self.text_edit.textCursor().block().position() != self._editing_hr_pos:
            self._finish_hr_edit()

    def _autoformat_hr(self) -> bool:
        if self._source_mode:
            return False
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            return False
        if cursor.block().text().strip() not in {"---", "***", "___"}:
            return False
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.removeSelectedText()
        block_format = cursor.blockFormat()
        block_format.setProperty(
            QTextFormat.Property.BlockTrailingHorizontalRulerWidth, 1
        )
        block_format.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        cursor.setBlockFormat(block_format)
        cursor.insertBlock()
        cursor.setBlockFormat(QTextBlockFormat())
        cursor.endEditBlock()
        self._style_block(cursor.block())
        self._editing_hr_pos = None
        self.text_edit.setTextCursor(cursor)
        return True

    def _autoformat_prefix(self) -> bool:
        if self._source_mode:
            return False
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            return False
        block = cursor.block()
        offset = cursor.position() - block.position()
        if offset <= 0:
            return False
        prefix = block.text()[:offset]
        heading = re.fullmatch(r"(#{1,6})\s", prefix)
        task = re.fullmatch(r"- \[([ xX])\]\s", prefix)
        bullet = re.fullmatch(r"[-*+]\s", prefix)
        ordered = re.fullmatch(r"\d+\.\s", prefix)
        code = prefix == "```"
        if not (heading or task or bullet or ordered or code or prefix == "> "):
            return False
        cursor.beginEditBlock()
        cursor.setPosition(block.position())
        cursor.setPosition(block.position() + len(prefix), QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        block_format = cursor.blockFormat()
        char_format = QTextCharFormat()
        if heading:
            level = len(heading.group(1))
            block_format.setHeadingLevel(level)
            cursor.setBlockFormat(block_format)
            if level == 1:
                char_format.setFontPointSize(26)
            elif level == 2:
                char_format.setFontPointSize(21)
            else:
                char_format.setFontPointSize(18)
            char_format.setFontWeight(QFont.Weight.Bold)
            cursor.mergeCharFormat(char_format)
        elif prefix == "> ":
            block_format.setProperty(QTextFormat.Property.BlockQuoteLevel, 1)
            cursor.setBlockFormat(block_format)
        elif code:
            block_format.setProperty(QTextFormat.Property.BlockCodeLanguage, "text")
            block_format.setNonBreakableLines(True)
            cursor.setBlockFormat(block_format)
        else:
            list_format = QTextListFormat()
            list_format.setIndent(1)
            if ordered:
                list_format.setStyle(QTextListFormat.Style.ListDecimal)
            else:
                list_format.setStyle(QTextListFormat.Style.ListDisc)
            cursor.createList(list_format)
            if task:
                cursor.insertText(f"[{task.group(1)}] ")
        cursor.endEditBlock()
        self._style_block(cursor.block())
        self.text_edit.setTextCursor(cursor)
        return True

    def _selected_blocks(self) -> list[QTextBlock]:
        cursor = self._cursor()
        document = self.text_edit.document()
        block = document.findBlock(cursor.selectionStart())
        last = document.findBlock(cursor.selectionEnd())
        blocks: list[QTextBlock] = []
        while block.isValid():
            blocks.append(block)
            if block == last:
                break
            block = block.next()
        return blocks

    def _source_prefix(self, prefix: str, toggle: bool = True) -> None:
        cursor = self.source_edit.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        block_cursor = QTextCursor(cursor)
        block_cursor.setPosition(start)
        block_cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        block_cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        block_cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        text = block_cursor.selectedText().replace("\u2029", "\n")
        lines = text.split("\n")
        if toggle and lines and all(line.startswith(prefix) for line in lines if line.strip()):
            new_lines = [line[len(prefix) :] if line.startswith(prefix) else line for line in lines]
        else:
            new_lines = [prefix + line if line.strip() else line for line in lines]
        block_cursor.insertText("\n".join(new_lines))

    def _toggle_quote(self) -> None:
        if self._source_mode:
            self._source_prefix("> ")
            return
        blocks = self._selected_blocks()
        if not blocks:
            return
        current = blocks[0].blockFormat().property(QTextFormat.Property.BlockQuoteLevel) or 0
        level = 0 if current else 1
        for block in blocks:
            cursor = QTextCursor(block)
            fmt = block.blockFormat()
            fmt.setProperty(QTextFormat.Property.BlockQuoteLevel, level)
            cursor.setBlockFormat(fmt)
        self.text_edit.setFocus()

    def _toggle_block_code(self) -> None:
        if self._source_mode:
            cursor = self.source_edit.textCursor()
            selected = cursor.selectedText()
            if selected:
                cursor.insertText(f"```text\n{selected}\n```")
            else:
                cursor.insertText("```text\n\n```")
                cursor.movePosition(QTextCursor.MoveOperation.Up)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfLine)
                self.source_edit.setTextCursor(cursor)
            return
        blocks = self._selected_blocks()
        if not blocks:
            return
        is_code = any(
            block.blockFormat().property(QTextFormat.Property.BlockCodeLanguage)
            for block in blocks
        )
        for block in blocks:
            cursor = QTextCursor(block)
            fmt = block.blockFormat()
            if is_code:
                fmt.clearProperty(QTextFormat.Property.BlockCodeLanguage)
                fmt.setNonBreakableLines(False)
            else:
                fmt.setProperty(QTextFormat.Property.BlockCodeLanguage, "text")
                fmt.setNonBreakableLines(True)
            cursor.setBlockFormat(fmt)
        self.text_edit.setFocus()

    def _insert_task_list(self) -> None:
        if self._source_mode:
            self._source_prefix("- [ ] ", toggle=False)
            return
        cursor = self._cursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        if not cursor.block().text().startswith("[ ]"):
            cursor.insertText("[ ] ")
        list_format = QTextListFormat()
        list_format.setStyle(QTextListFormat.Style.ListDisc)
        list_format.setIndent(1)
        cursor.createList(list_format)
        self.text_edit.setFocus()

    def _insert_table(self) -> None:
        if self._source_mode:
            template = "| 列 1 | 列 2 |\n| --- | --- |\n|  |  |\n"
            self.source_edit.textCursor().insertText(template)
            return
        rows, ok = QInputDialog.getInt(self, "插入表格", "行数（含表头）：", 2, 1, 50)
        if not ok:
            return
        columns, ok = QInputDialog.getInt(self, "插入表格", "列数：", 2, 1, 20)
        if not ok:
            return
        table_format = QTextTableFormat()
        table_format.setBorder(1)
        table_format.setCellSpacing(0)
        table_format.setCellPadding(4)
        table_format.setWidth(
            QTextLength(QTextLength.Type.PercentageLength, 100)
        )
        table = self._cursor().insertTable(rows, columns, table_format)
        self._set_table_alignments(
            table, ["left" for _ in range(columns)], restyle=False
        )
        end_cursor = table.lastCursorPosition()
        end_cursor.insertBlock()
        self.text_edit.setTextCursor(end_cursor)
        self.text_edit.setFocus()

    def _current_table(self):
        cursor = self.text_edit.textCursor()
        table = cursor.currentTable()
        if table is None:
            return None, None
        cell = table.cellAt(cursor)
        return table, cell

    def _table_edit(self, operation) -> bool:
        table, cell = self._current_table()
        if table is None or cell is None:
            return False
        cursor = self.text_edit.textCursor()
        cursor.beginEditBlock()
        try:
            operation(table, cell)
        finally:
            cursor.endEditBlock()
        self._style_tables()
        self.text_edit.setFocus()
        return True

    def _table_insert_row(self, offset: int) -> None:
        self._table_edit(
            lambda table, cell: table.insertRows(cell.row() + offset, 1)
        )

    def _table_delete_row(self) -> None:
        def operation(table, cell):
            if table.rows() > 1:
                table.removeRows(cell.row(), 1)

        self._table_edit(operation)

    def _table_insert_column(self, offset: int) -> None:
        self._table_edit(
            lambda table, cell: table.insertColumns(cell.column() + offset, 1)
        )

    def _table_delete_column(self) -> None:
        def operation(table, cell):
            if table.columns() > 1:
                table.removeColumns(cell.column(), 1)

        self._table_edit(operation)

    @staticmethod
    def _parse_table_alignments(text: str) -> list[list[str]]:
        lines = text.splitlines()
        results: list[list[str]] = []
        in_fence = False
        fence = ""
        separator = re.compile(
            r"^\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?$"
        )
        index = 0
        while index < len(lines) - 1:
            stripped = lines[index].strip()
            if stripped.startswith(("```", "~~~")):
                marker = stripped[:3]
                if not in_fence:
                    in_fence = True
                    fence = marker
                elif stripped.startswith(fence):
                    in_fence = False
                index += 1
                continue
            if (
                not in_fence
                and stripped.startswith("|")
                and separator.match(lines[index + 1].strip())
            ):
                cells = [
                    cell.strip()
                    for cell in lines[index + 1].strip().strip("|").split("|")
                ]
                alignments = []
                for cell in cells:
                    left = cell.startswith(":")
                    right = cell.endswith(":")
                    if left and right:
                        alignments.append("center")
                    elif right:
                        alignments.append("right")
                    else:
                        alignments.append("left")
                results.append(alignments)
                index += 2
                continue
            index += 1
        return results

    def _table_alignments(self, table: QTextTable) -> list[str]:
        raw = table.format().property(TABLE_ALIGN_PROPERTY)
        if isinstance(raw, int):
            values = []
            for column in range(table.columns()):
                code = (raw >> (column * 2)) & 0b11
                values.append({1: "center", 2: "right"}.get(code, "left"))
            return values
        return ["left" for _ in range(table.columns())]

    @staticmethod
    def _apply_cell_alignment(table: QTextTable, alignments: list[str]) -> None:
        mapping = {
            "left": Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
        }
        for column, alignment in enumerate(alignments):
            flag = mapping.get(alignment, Qt.AlignmentFlag.AlignLeft)
            for row in range(table.rows()):
                cursor = table.cellAt(row, column).firstCursorPosition()
                block_format = cursor.blockFormat()
                block_format.setAlignment(flag)
                cursor.setBlockFormat(block_format)

    def _apply_table_alignments(self) -> None:
        for index, table in enumerate(self._collect_tables()):
            if index < len(self._parsed_table_alignments):
                alignments = self._parsed_table_alignments[index]
                if len(alignments) != table.columns():
                    alignments = ["left" for _ in range(table.columns())]
            else:
                alignments = ["left" for _ in range(table.columns())]
            self._set_table_alignments(table, alignments, restyle=False)

    def _set_table_alignments(
        self, table: QTextTable, alignments: list[str], restyle: bool = True
    ) -> None:
        codes = {"left": 0, "center": 1, "right": 2}
        encoded = 0
        for index, alignment in enumerate(alignments):
            encoded |= codes.get(alignment, 0) << (index * 2)
        fmt = table.format()
        fmt.setProperty(TABLE_ALIGN_PROPERTY, encoded)
        table.setFormat(fmt)
        self._apply_cell_alignment(table, alignments)
        if restyle:
            self._style_tables()

    def _table_set_alignment(self, alignment: str) -> None:
        table, cell = self._current_table()
        if table is None or cell is None:
            return
        alignments = self._table_alignments(table)
        alignments[cell.column()] = alignment
        self._set_table_alignments(table, alignments)

    def _table_delete(self) -> None:
        table, _cell = self._current_table()
        if table is None:
            return
        cursor = QTextCursor(table.firstCursorPosition())
        cursor.setPosition(
            table.lastCursorPosition().position(), QTextCursor.MoveMode.KeepAnchor
        )
        cursor.removeSelectedText()
        self.text_edit.setFocus()

    def _show_editor_menu(self, point) -> None:
        menu = QMenu(self.text_edit)
        for label, slot in (
            ("撤销", self.text_edit.undo),
            ("重做", self.text_edit.redo),
        ):
            action = QAction(label, menu)
            action.triggered.connect(slot)
            menu.addAction(action)
        menu.addSeparator()
        for label, slot in (
            ("剪切", self.text_edit.cut),
            ("复制", self.text_edit.copy),
            ("粘贴", self.text_edit.paste),
            ("全选", self.text_edit.selectAll),
        ):
            action = QAction(label, menu)
            action.triggered.connect(slot)
            menu.addAction(action)
        table, _cell = self._current_table()
        if table is not None:
            menu.addSeparator()
            for label, slot in (
                ("在上方插入行", lambda: self._table_insert_row(0)),
                ("在下方插入行", lambda: self._table_insert_row(1)),
                ("删除当前行", self._table_delete_row),
                ("在左侧插入列", lambda: self._table_insert_column(0)),
                ("在右侧插入列", lambda: self._table_insert_column(1)),
                ("删除当前列", self._table_delete_column),
            ):
                action = QAction(label, menu)
                action.triggered.connect(slot)
                menu.addAction(action)
            menu.addSeparator()
            for label, slot in (
                ("左对齐", lambda: self._table_set_alignment("left")),
                ("居中对齐", lambda: self._table_set_alignment("center")),
                ("右对齐", lambda: self._table_set_alignment("right")),
                ("删除表格", self._table_delete),
            ):
                action = QAction(label, menu)
                action.triggered.connect(slot)
                menu.addAction(action)
        menu.exec(self.text_edit.mapToGlobal(point))

    def _insert_image(self) -> None:
        url, ok = QInputDialog.getText(self, "插入图片", "图片路径或 URL：")
        if not ok or not url.strip():
            return
        alt, ok = QInputDialog.getText(self, "插入图片", "替代文字（可留空）：")
        if not ok:
            return
        if self._source_mode:
            self.source_edit.textCursor().insertText(
                f"![{alt.strip()}]({url.strip()})"
            )
            return
        image_format = QTextImageFormat()
        image_format.setName(url.strip())
        image_format.setProperty(QTextFormat.Property.ImageAltText, alt.strip())
        self._cursor().insertImage(image_format)
        self.text_edit.setFocus()

    def _insert_hr(self) -> None:
        if self._source_mode:
            self.source_edit.textCursor().insertText("\n---\n")
            return
        cursor = self._cursor()
        cursor.insertBlock()
        block_format = cursor.blockFormat()
        block_format.setProperty(
            QTextFormat.Property.BlockTrailingHorizontalRulerWidth, 1
        )
        block_format.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        cursor.setBlockFormat(block_format)
        cursor.insertBlock()
        cursor.setBlockFormat(QTextBlockFormat())
        self._style_block(cursor.block())
        self.text_edit.setTextCursor(cursor)
        self.text_edit.setFocus()

    def set_title_heading(self, title: str) -> None:
        if not self._injected_title:
            return
        block = self.text_edit.document().firstBlock()
        if block.blockFormat().headingLevel() != 1:
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock,
            QTextCursor.MoveMode.KeepAnchor,
        )
        cursor.insertText(title)

    def _clear_format(self) -> None:
        if self._source_mode:
            return
        cursor = self._cursor()
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Normal)
        fmt.setFontItalic(False)
        fmt.setFontStrikeOut(False)
        fmt.setFontUnderline(False)
        fmt.setAnchor(False)
        fmt.setFontFixedPitch(False)
        fmt.setFontFamilies([])
        if cursor.hasSelection():
            cursor.setCharFormat(fmt)
        else:
            self.text_edit.setCurrentCharFormat(fmt)
        for block in self._selected_blocks():
            block_cursor = QTextCursor(block)
            block_format = block.blockFormat()
            block_format.setHeadingLevel(0)
            block_format.clearProperty(QTextFormat.Property.BlockQuoteLevel)
            block_format.clearProperty(QTextFormat.Property.BlockCodeLanguage)
            block_format.setNonBreakableLines(False)
            block_cursor.setBlockFormat(block_format)
        self.text_edit.setFocus()

    # ----------------------------------------------------------------- focus
    def focus_editor(self) -> None:
        (self.source_edit if self._source_mode else self.text_edit).setFocus()

    def go_to_line(self, line: int) -> None:
        if not self._source_mode:
            return
        cursor = self.source_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        for _ in range(max(0, line - 1)):
            cursor.movePosition(QTextCursor.MoveOperation.Down)
        self.source_edit.setTextCursor(cursor)
        self.source_edit.centerCursor()
