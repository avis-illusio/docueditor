"""Import wizard: choose a source, preview the plan, then execute."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..importers import base, novelwriter, yuque
from ..project import DocusaurusProject


class ImportDialog(QDialog):
    imported = Signal(object)  # base.ImportResult

    def __init__(self, project: DocusaurusProject, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self._plan: base.ImportPlan | None = None
        self._planned: list[base.PlannedFile] = []
        self.setWindowTitle("导入文档")
        self.setMinimumSize(760, 560)

        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["Novelwriter", "语雀（Yuque）"])

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择 .nwd 项目目录，或语雀导出的文件夹 / ZIP / Markdown")
        browse_dir = QPushButton("文件夹…")
        browse_dir.clicked.connect(self._browse_dir)
        browse_file = QPushButton("文件…")
        browse_file.clicked.connect(self._browse_file)

        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse_dir)
        path_row.addWidget(browse_file)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("追加模式（默认，不覆盖已有文件）", base.APPEND)
        self.mode_combo.addItem("替换模式（覆盖同名文件，先自动备份）", base.REPLACE)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        self.replace_confirm = QCheckBox("我确认允许覆盖同名文档（原文件会备份到 .docueditor-backup/）")
        self.replace_confirm.setChecked(False)
        self.replace_confirm.setEnabled(False)

        form = QFormLayout()
        form.addRow("来源类型", self.kind_combo)
        form.addRow("来源路径", path_row)
        form.addRow("导入模式", self.mode_combo)
        form.addRow("", self.replace_confirm)

        self.preview_button = QPushButton("预演导入")
        self.preview_button.clicked.connect(self._preview)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["目标文件", "标题", "sidebar_position", "动作"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        self.summary_label = QLabel("尚未预演")
        self.warnings = QTextEdit()
        self.warnings.setReadOnly(True)
        self.warnings.setMaximumHeight(110)
        self.warnings.setPlaceholderText("导入警告会显示在这里")

        self.buttons = QDialogButtonBox()
        self.import_button = self.buttons.addButton("执行导入", QDialogButtonBox.ButtonRole.AcceptRole)
        self.import_button.setEnabled(False)
        self.close_button = self.buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.accepted.connect(self._execute)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addLayout(form)
        layout.addWidget(self.preview_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table, 1)
        layout.addWidget(QLabel("警告"))
        layout.addWidget(self.warnings)
        layout.addWidget(self.buttons)

    # ----------------------------------------------------------------- paths
    def _browse_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择来源文件夹", str(self.project.root))
        if directory:
            self.path_edit.setText(directory)

    def _browse_file(self) -> None:
        filters = "Markdown / ZIP (*.md *.markdown *.txt *.zip);;所有文件 (*)"
        path, _ = QFileDialog.getOpenFileName(self, "选择来源文件", str(self.project.root), filters)
        if path:
            self.path_edit.setText(path)

    def _mode(self) -> str:
        return self.mode_combo.currentData()

    def _on_mode_changed(self) -> None:
        replace = self._mode() == base.REPLACE
        self.replace_confirm.setEnabled(replace)
        if not replace:
            self.replace_confirm.setChecked(False)
        self._plan = None
        self._planned = []
        self.import_button.setEnabled(False)
        self.summary_label.setText("模式已切换，请重新预演")

    # --------------------------------------------------------------- preview
    def _load_plan(self) -> base.ImportPlan:
        raw = self.path_edit.text().strip()
        if not raw:
            raise ValueError("请先选择来源路径")
        path = Path(raw).expanduser()
        if not path.exists():
            raise ValueError(f"路径不存在：{path}")
        if self.kind_combo.currentIndex() == 0:
            return novelwriter.load(path)
        return yuque.load(path)

    def _preview(self) -> None:
        try:
            plan = self._load_plan()
            planned = base.plan_import(self.project, plan, self._mode())
        except (ValueError, FileNotFoundError, OSError) as exc:
            QMessageBox.warning(self, "预演失败", str(exc))
            return
        self._plan = plan
        self._planned = planned
        self.table.setRowCount(0)
        for row in planned:
            index = self.table.rowCount()
            self.table.insertRow(index)
            self.table.setItem(index, 0, QTableWidgetItem(row.rel))
            self.table.setItem(index, 1, QTableWidgetItem(row.title))
            self.table.setItem(index, 2, QTableWidgetItem(str(row.position)))
            action = "覆盖" if row.action == "overwrite" else "新建"
            item = QTableWidgetItem(action)
            if row.action == "overwrite":
                item.setForeground(Qt.GlobalColor.darkRed)
            self.table.setItem(index, 3, item)
        self.summary_label.setText(
            f"{plan.kind}：共 {len(plan.items)} 篇，预计新建 "
            f"{sum(1 for row in planned if row.action == 'create')} 篇，覆盖 "
            f"{sum(1 for row in planned if row.action == 'overwrite')} 篇，"
            f"{len(plan.warnings)} 条警告"
        )
        self.warnings.setPlainText("\n".join(plan.warnings))
        self.import_button.setEnabled(bool(planned))

    # --------------------------------------------------------------- execute
    def _execute(self) -> None:
        if self._plan is None:
            self._preview()
        if self._plan is None or not self._planned:
            return
        if self._mode() == base.REPLACE and not self.replace_confirm.isChecked():
            QMessageBox.warning(self, "替换模式", "请勾选覆盖确认复选框后再执行。")
            return
        try:
            result = base.execute_import(self.project, self._plan, self._mode())
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            QMessageBox.critical(self, "导入失败", str(exc))
            return
        lines = [
            f"新建：{len(result.created)} 篇",
            f"覆盖：{len(result.overwritten)} 篇",
        ]
        if result.backup_root is not None:
            lines.append(f"备份目录：{result.backup_root}")
        if result.warnings:
            lines.append(f"警告：{len(result.warnings)} 条（见导入日志）")
        QMessageBox.information(self, "导入完成", "\n".join(lines))
        self.imported.emit(result)
        self.accept()
