"""Dialog for creating a folder with a sidebar label."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


class NewFolderDialog(QDialog):
    """Folder name first, sidebar title below (title follows until edited)."""

    def __init__(self, parent: QWidget | None = None, directory: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("新建文件夹")
        self.setMinimumWidth(460)
        self._title_touched = False

        self.folder_edit = QLineEdit("新建文件夹")
        self.folder_edit.selectAll()
        self.folder_edit.setPlaceholderText("文件夹名（用于路径）")

        self.title_edit = QLineEdit("新建文件夹")
        self.title_edit.setPlaceholderText("侧边栏标题")
        self.location_label = QLabel(directory or "docs")
        self.location_label.setObjectName("pathLabel")

        form = QFormLayout()
        form.setSpacing(8)
        form.addRow("文件夹名", self.folder_edit)
        form.addRow("标题", self.title_edit)
        form.addRow("位置", self.location_label)

        hint = QLabel("标题默认跟随文件夹名；手动修改标题后不再自动同步。")
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

        self.folder_edit.textChanged.connect(self._sync_title)
        self.title_edit.textEdited.connect(self._title_edited)

    def _title_edited(self, _text: str) -> None:
        self._title_touched = True

    def _sync_title(self, text: str) -> None:
        if self._title_touched:
            return
        self.title_edit.setText(text.strip() or "新建文件夹")

    def values(self) -> tuple[str, str]:
        name = self.folder_edit.text().strip() or "新建文件夹"
        title = self.title_edit.text().strip() or name
        return name, title

    @staticmethod
    def ask(parent: QWidget | None, directory: str = "") -> tuple[str, str] | None:
        dialog = NewFolderDialog(parent, directory)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, title = dialog.values()
            if name:
                return name, title
        return None
