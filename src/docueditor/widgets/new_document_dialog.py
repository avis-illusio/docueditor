"""Dialog for creating a new document with an explicit filename and title."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


class NewDocumentDialog(QDialog):
    """Filename first, title below; title follows filename until edited."""

    def __init__(self, parent: QWidget | None = None, directory: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("新建文档")
        self.setMinimumWidth(460)
        self._title_touched = False

        self.filename_edit = QLineEdit("untitled")
        self.filename_edit.selectAll()
        self.filename_edit.setPlaceholderText("文件名（不含扩展名）")

        suffix = QLabel(".mdx")
        suffix.setObjectName("pathLabel")
        filename_row = QHBoxLayout()
        filename_row.setContentsMargins(0, 0, 0, 0)
        filename_row.addWidget(self.filename_edit, 1)
        filename_row.addWidget(suffix)

        self.title_edit = QLineEdit("untitled")
        self.title_edit.setPlaceholderText("侧边栏标题")
        self.location_label = QLabel(directory or "docs")
        self.location_label.setObjectName("pathLabel")

        form = QFormLayout()
        form.setSpacing(8)
        form.addRow("文件名", filename_row)
        form.addRow("标题", self.title_edit)
        form.addRow("位置", self.location_label)

        hint = QLabel("标题默认跟随文件名；手动修改标题后不再自动同步。")
        hint.setObjectName("pathLabel")
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

        self.filename_edit.textChanged.connect(self._sync_title)
        self.title_edit.textEdited.connect(self._title_edited)

    def _title_edited(self, _text: str) -> None:
        self._title_touched = True

    def _sync_title(self, text: str) -> None:
        if self._title_touched:
            return
        stem = text.strip()
        if stem.lower().endswith((".md", ".mdx")):
            stem = stem.rsplit(".", 1)[0]
        self.title_edit.setText(stem.replace("-", " ").strip() or "untitled")

    def values(self) -> tuple[str, str]:
        stem = self.filename_edit.text().strip()
        if stem.lower().endswith((".md", ".mdx")):
            stem = stem.rsplit(".", 1)[0]
        title = self.title_edit.text().strip() or stem
        return stem, title

    @staticmethod
    def ask(parent: QWidget | None, directory: str = "") -> tuple[str, str] | None:
        dialog = NewDocumentDialog(parent, directory)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            stem, title = dialog.values()
            if stem:
                return stem, title
        return None
