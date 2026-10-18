"""The rich-text Markdown editor widget.

The WYSIWYG view is a ``QTextEdit`` driven by Qt's Markdown document model.
Constructs that Qt cannot represent (fenced code with a language tag, MDX
imports, JSX, admonitions) are replaced by tokens and restored on save, so
saving never destroys them.  A plain-source view is available for direct
editing.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QFont,
    QKeySequence,
    QShortcut,
    QTextBlock,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
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

GITHUB_DIALECT = getattr(
    QTextDocument,
    "MarkdownDialectGitHub",
    getattr(getattr(QTextDocument, "MarkdownFeature", object), "MarkdownDialectGitHub", 0),
)


def _feature_markdown() -> int:
    return GITHUB_DIALECT


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

        self.text_edit = QTextEdit()
        self.text_edit.setAcceptRichText(True)
        self.text_edit.setPlaceholderText("在这里开始书写……")
        self.text_edit.setTabChangesFocus(False)
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
        self.hint = QLabel("")
        self.hint.setObjectName("editorHint")
        self.hint.setWordWrap(True)
        self.hint.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.hint)
        layout.addWidget(self.stack, 1)

        self.text_edit.textChanged.connect(self._on_changed)
        self.source_edit.textChanged.connect(self._on_changed)
        self.text_edit.document().modificationChanged.connect(self._emit_modified)
        self.source_edit.document().modificationChanged.connect(self._emit_modified)
        self.text_edit.cursorPositionChanged.connect(self._emit_cursor)
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
        self._pending_overrides = {}
        self._front_matter = frontmatter.split(text)
        body = self._prepare_body(self._front_matter)
        self._protected = mdx_guard.protect(body)
        self.text_edit.document().setMarkdown(self._protected.text, _feature_markdown())
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

    def current_text(self) -> str:
        if self._source_mode:
            return self.source_edit.toPlainText()
        markdown = self.text_edit.document().toMarkdown(_feature_markdown())
        restored = mdx_guard.restore(markdown, self._protected)
        restored = self._replace_tables(restored)
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
        lines = [
            "| " + " | ".join(data[0]) + " |",
            "| " + " | ".join("---" for _ in range(columns)) + " |",
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
            body = self._prepare_body(self._front_matter)
            self._protected = mdx_guard.protect(body)
            self.text_edit.document().setMarkdown(self._protected.text, _feature_markdown())
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
        end_cursor = table.lastCursorPosition()
        end_cursor.insertBlock()
        self.text_edit.setTextCursor(end_cursor)
        self.text_edit.setFocus()

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
        cursor.setBlockFormat(block_format)
        cursor.insertBlock()
        cursor.setBlockFormat(QTextBlockFormat())
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
