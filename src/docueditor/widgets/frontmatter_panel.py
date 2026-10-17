"""Right-hand panel for editing a document's front matter."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..project import DocEntry


class FrontMatterPanel(QWidget):
    applyRequested = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entry: DocEntry | None = None

        self.path_label = QLabel("未选择文档")
        self.path_label.setObjectName("pathLabel")
        self.path_label.setWordWrap(True)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("文档标题")
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("自定义 id（可留空）")
        self.slug_edit = QLineEdit()
        self.slug_edit.setPlaceholderText("自定义 URL slug（可留空）")
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("标签，用逗号分隔")
        self.position_spin = QSpinBox()
        self.position_spin.setRange(-1, 99999)
        self.position_spin.setSpecialValueText("未设置")
        self.position_spin.setValue(-1)
        self.draft_check = QCheckBox("草稿（draft）")

        form = QFormLayout()
        form.setLabelAlignment(form.labelAlignment())
        form.setSpacing(8)
        form.addRow("标题 title", self.title_edit)
        form.addRow("标识 id", self.id_edit)
        form.addRow("路径 slug", self.slug_edit)
        form.addRow("标签 tags", self.tags_edit)
        form.addRow("排序 position", self.position_spin)
        form.addRow("", self.draft_check)

        self.extra_label = QLabel("")
        self.extra_label.setWordWrap(True)
        self.extra_label.setObjectName("extraFields")

        self.apply_button = QPushButton("应用到文档")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self.path_label)
        layout.addWidget(separator)
        layout.addLayout(form)
        layout.addWidget(self.extra_label)
        layout.addStretch(1)
        layout.addWidget(self.apply_button)

    def set_document(self, entry: DocEntry | None) -> None:
        self._entry = entry
        enabled = entry is not None
        for widget in (
            self.title_edit,
            self.id_edit,
            self.slug_edit,
            self.tags_edit,
            self.position_spin,
            self.draft_check,
        ):
            widget.setEnabled(enabled)
        self.apply_button.setEnabled(enabled)
        if entry is None:
            self.path_label.setText("未选择文档")
            for widget in (self.title_edit, self.id_edit, self.slug_edit, self.tags_edit):
                widget.clear()
            self.position_spin.setValue(-1)
            self.draft_check.setChecked(False)
            self.extra_label.clear()
            return
        values = entry.front_matter.values
        self.path_label.setText(f"{entry.rel}\n{entry.path}")
        self.title_edit.setText(str(values.get("title") or entry.title))
        self.id_edit.setText(str(values.get("id") or ""))
        self.slug_edit.setText(str(values.get("slug") or ""))
        tags = values.get("tags")
        if isinstance(tags, (list, tuple)):
            self.tags_edit.setText(", ".join(str(tag) for tag in tags))
        elif tags:
            self.tags_edit.setText(str(tags))
        else:
            self.tags_edit.clear()
        position = entry.position if entry.position is not None else -1
        self.position_spin.setValue(position)
        self.draft_check.setChecked(bool(values.get("draft")))
        ignored = [key for key in values if key not in {"title", "id", "slug", "tags", "sidebar_position", "draft"}]
        if ignored:
            self.extra_label.setText("保留的其他字段：" + "、".join(sorted(ignored)))
        else:
            self.extra_label.clear()

    def values(self) -> dict[str, object]:
        title = self.title_edit.text().strip()
        doc_id = self.id_edit.text().strip()
        slug = self.slug_edit.text().strip()
        tags = [tag.strip() for tag in self.tags_edit.text().replace("，", ",").split(",") if tag.strip()]
        position = self.position_spin.value()
        return {
            "title": title or None,
            "id": doc_id or None,
            "slug": slug or None,
            "tags": tags or None,
            "sidebar_position": position if position >= 0 else None,
            "draft": True if self.draft_check.isChecked() else None,
        }

    def _apply(self) -> None:
        if self._entry is None:
            return
        self.applyRequested.emit(self.values())
