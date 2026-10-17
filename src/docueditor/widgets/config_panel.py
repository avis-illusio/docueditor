"""Project configuration panel: site config + package metadata."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..config_editor import (
    SITE_KEYS,
    KEY_LABELS,
    read_package_json,
    read_site_config,
    update_package_json,
    update_site_config,
)
from ..project import DocusaurusProject


class ConfigPanel(QWidget):
    saved = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project: DocusaurusProject | None = None
        self._site_edits: dict[str, QLineEdit] = {}
        self._package_edits: dict[str, QLineEdit] = {}

        self.path_label = QLabel("未打开项目")
        self.path_label.setObjectName("pathLabel")
        self.path_label.setWordWrap(True)

        form = QFormLayout()
        form.setSpacing(8)
        for key in SITE_KEYS:
            edit = QLineEdit()
            edit.setPlaceholderText(key)
            self._site_edits[key] = edit
            form.addRow(KEY_LABELS.get(key, key), edit)

        self.package_label = QLabel("")
        self.package_label.setObjectName("sectionLabel")
        package_form = QFormLayout()
        package_form.setSpacing(8)
        for key, label in (
            ("name", "包名 name"),
            ("version", "版本 version"),
            ("description", "描述 description"),
        ):
            edit = QLineEdit()
            edit.setPlaceholderText(key)
            self._package_edits[key] = edit
            package_form.addRow(label, edit)

        self.save_button = QPushButton("保存配置")
        self.save_button.clicked.connect(self._save)
        self.reload_button = QPushButton("重新载入")
        self.reload_button.clicked.connect(self._reload)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        content_layout.addWidget(self.path_label)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        content_layout.addWidget(divider)
        content_layout.addLayout(form)
        content_layout.addWidget(self.package_label)
        content_layout.addLayout(package_form)
        content_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.reload_button)
        layout.addWidget(self.save_button)

    def set_project(self, project: DocusaurusProject | None) -> None:
        self._project = project
        self._reload()

    def _reload(self) -> None:
        enabled = self._project is not None and self._project.config_path is not None
        self.save_button.setEnabled(enabled)
        self.reload_button.setEnabled(enabled)
        for edit in list(self._site_edits.values()) + list(self._package_edits.values()):
            edit.setEnabled(enabled)
        if not enabled or self._project is None or self._project.config_path is None:
            self.path_label.setText("未打开项目")
            for edit in self._site_edits.values():
                edit.clear()
            for edit in self._package_edits.values():
                edit.clear()
            self.package_label.setText("")
            return
        values = read_site_config(self._project.config_path)
        self.path_label.setText(str(self._project.config_path))
        for key, edit in self._site_edits.items():
            edit.setText(values.get(key, ""))
        package_path = self._project.root / "package.json"
        package_values = read_package_json(package_path)
        self.package_label.setText(f"package.json：{package_path if package_path.is_file() else '不存在'}")
        for key, edit in self._package_edits.items():
            edit.setText(package_values.get(key, ""))
        for edit in self._package_edits.values():
            edit.setEnabled(package_path.is_file())

    def _save(self) -> None:
        if self._project is None or self._project.config_path is None:
            return
        site_values = {key: edit.text() for key, edit in self._site_edits.items()}
        changed = update_site_config(self._project.config_path, site_values)
        package_path = self._project.root / "package.json"
        package_changed: list[str] = []
        if package_path.is_file():
            package_values = {key: edit.text() for key, edit in self._package_edits.items()}
            try:
                package_changed = update_package_json(package_path, package_values)
            except ValueError as exc:
                QMessageBox.warning(self, "package.json", str(exc))
        self.saved.emit(changed + [f"package.json:{key}" for key in package_changed])
        if not changed and not package_changed:
            QMessageBox.information(self, "配置", "没有需要保存的改动。")
