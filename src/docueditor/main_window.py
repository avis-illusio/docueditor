"""Main application window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .project import DocusaurusProject, DocEntry, ProjectError, scaffold_project
from .utils import read_text
from .widgets.config_panel import ConfigPanel
from .widgets.editor import MarkdownEditor
from .widgets.file_tree import FileTree
from .widgets.frontmatter_panel import FrontMatterPanel
from .widgets.import_dialog import ImportDialog

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project: DocusaurusProject | None = None
        self.current_entry: DocEntry | None = None
        self._settings = QSettings("avis-illusio", "docueditor")
        self.setWindowTitle("Docueditor")
        self.resize(1280, 820)

        self.editor = MarkdownEditor()
        self.file_tree = FileTree()
        self.front_matter_panel = FrontMatterPanel()
        self.config_panel = ConfigPanel()

        self.empty_page = self._build_empty_page()
        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(self.empty_page)
        self.center_stack.addWidget(self.editor)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.center_stack)
        splitter.setStretchFactor(0, 1)
        self.setCentralWidget(splitter)

        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._connect_signals()
        self._set_project_enabled(False)

    # ------------------------------------------------------------------- ui
    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Docueditor")
        title.setObjectName("emptyTitle")
        subtitle = QLabel("打开一个 Docusaurus 项目，或新建一个文档站。")
        subtitle.setObjectName("emptySubtitle")
        hint = QLabel("文件 → 打开 Docusaurus 项目…")
        hint.setObjectName("emptyHint")
        for widget in (title, subtitle, hint):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(hint)
        return page

    def _build_docks(self) -> None:
        self.tree_dock = QDockWidget("文档", self)
        self.tree_dock.setObjectName("treeDock")
        self.tree_dock.setWidget(self.file_tree)
        self.tree_dock.setMinimumWidth(240)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.tree_dock)

        self.right_dock = QDockWidget("属性", self)
        self.right_dock.setObjectName("rightDock")
        self.right_dock.setMinimumWidth(300)
        self.props_tabs = QTabWidget()
        self.props_tabs.addTab(self.front_matter_panel, "Front Matter")
        self.props_tabs.addTab(self.config_panel, "项目配置")
        self.right_dock.setWidget(self.props_tabs)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.right_dock)
        self.resizeDocks(
            [self.tree_dock, self.right_dock], [270, 330], Qt.Orientation.Horizontal
        )

    def _build_actions(self) -> None:
        self.action_new_project = QAction("新建项目…", self)
        self.action_new_project.setShortcut(QKeySequence.StandardKey.New)
        self.action_new_project.triggered.connect(self.new_project)

        self.action_open_project = QAction("打开 Docusaurus 项目…", self)
        self.action_open_project.setShortcut(QKeySequence("Ctrl+O"))
        self.action_open_project.triggered.connect(self.open_project)

        self.action_new_doc = QAction("新建文档…", self)
        self.action_new_doc.setShortcut(QKeySequence("Ctrl+N"))
        self.action_new_doc.triggered.connect(lambda: self.new_document(""))

        self.action_save = QAction("保存", self)
        self.action_save.setShortcut(QKeySequence.StandardKey.Save)
        self.action_save.triggered.connect(self.save_current)

        self.action_import = QAction("导入…", self)
        self.action_import.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self.action_import.triggered.connect(self.import_content)

        self.action_quit = QAction("退出", self)
        self.action_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.action_quit.triggered.connect(self.close)

        self.action_refresh = QAction("刷新文件树", self)
        self.action_refresh.setShortcut(QKeySequence("F5"))
        self.action_refresh.triggered.connect(self.refresh_tree)

        self.action_source_mode = QAction("源码模式", self)
        self.action_source_mode.setCheckable(True)
        self.action_source_mode.setShortcut(QKeySequence("Ctrl+E"))
        self.action_source_mode.toggled.connect(self._toggle_source_mode)

        self.action_reveal_project = QAction("在文件管理器中打开项目", self)
        self.action_reveal_project.triggered.connect(self.reveal_project)

        self.action_config_tab = QAction("项目配置面板", self)
        self.action_config_tab.triggered.connect(lambda: self.props_tabs.setCurrentWidget(self.config_panel))

        self.action_about = QAction("关于 Docueditor", self)
        self.action_about.triggered.connect(self.show_about)

    def _build_menus(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("文件")
        file_menu.addAction(self.action_new_project)
        file_menu.addAction(self.action_open_project)
        file_menu.addSeparator()
        file_menu.addAction(self.action_new_doc)
        file_menu.addAction(self.action_save)
        file_menu.addSeparator()
        file_menu.addAction(self.action_import)
        file_menu.addSeparator()
        file_menu.addAction(self.action_quit)

        edit_menu = menu.addMenu("编辑")
        for label, standard, slot in (
            ("撤销", QKeySequence.StandardKey.Undo, self._edit_undo),
            ("重做", QKeySequence.StandardKey.Redo, self._edit_redo),
            ("剪切", QKeySequence.StandardKey.Cut, self._edit_cut),
            ("复制", QKeySequence.StandardKey.Copy, self._edit_copy),
            ("粘贴", QKeySequence.StandardKey.Paste, self._edit_paste),
            ("全选", QKeySequence.StandardKey.SelectAll, self._edit_select_all),
        ):
            action = QAction(label, self)
            action.setShortcut(standard)
            action.triggered.connect(slot)
            edit_menu.addAction(action)

        view_menu = menu.addMenu("视图")
        view_menu.addAction(self.action_source_mode)
        view_menu.addAction(self.action_refresh)
        view_menu.addAction(self.tree_dock.toggleViewAction())
        view_menu.addAction(self.right_dock.toggleViewAction())

        project_menu = menu.addMenu("项目")
        project_menu.addAction(self.action_config_tab)
        project_menu.addAction(self.action_reveal_project)

        help_menu = menu.addMenu("帮助")
        help_menu.addAction(self.action_about)

    def _edit_undo(self) -> None:
        self._active_edit_widget().undo()

    def _edit_redo(self) -> None:
        self._active_edit_widget().redo()

    def _edit_cut(self) -> None:
        self._active_edit_widget().cut()

    def _edit_copy(self) -> None:
        self._active_edit_widget().copy()

    def _edit_paste(self) -> None:
        self._active_edit_widget().paste()

    def _edit_select_all(self) -> None:
        self._active_edit_widget().selectAll()

    def _active_edit_widget(self):
        return self.editor.source_edit if self.editor.source_mode else self.editor.text_edit

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("主工具栏", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.addAction(self.action_open_project)
        toolbar.addAction(self.action_new_doc)
        toolbar.addAction(self.action_save)
        toolbar.addSeparator()
        toolbar.addAction(self.action_import)
        toolbar.addSeparator()
        toolbar.addAction(self.action_source_mode)
        self.addToolBar(toolbar)

    def _build_statusbar(self) -> None:
        status = QStatusBar()
        self.setStatusBar(status)
        self.status_project = QLabel("未打开项目")
        self.status_position = QLabel("")
        self.status_words = QLabel("0 字")
        status.addWidget(self.status_project, 1)
        status.addPermanentWidget(self.status_position)
        status.addPermanentWidget(self.status_words)

    def _connect_signals(self) -> None:
        self.file_tree.documentActivated.connect(self.open_document)
        self.file_tree.newDocumentRequested.connect(self.new_document)
        self.file_tree.renameRequested.connect(self.rename_document)
        self.file_tree.deleteRequested.connect(self.delete_document)
        self.file_tree.moveRequested.connect(self.move_document)
        self.file_tree.dropRequested.connect(self.handle_drop_move)
        self.file_tree.newChildDocumentRequested.connect(self.new_child_document)
        self.file_tree.revealRequested.connect(self.reveal_document)
        self.file_tree.refreshRequested.connect(self.refresh_tree)
        self.front_matter_panel.applyRequested.connect(self.apply_front_matter)
        self.config_panel.saved.connect(self._on_config_saved)
        self.editor.modifiedChanged.connect(self._on_modified)
        self.editor.wordCountChanged.connect(lambda count: self.status_words.setText(f"{count} 字"))
        self.editor.cursorPositionChanged.connect(
            lambda line, column: self.status_position.setText(f"行 {line}，列 {column}")
        )

    def _set_project_enabled(self, enabled: bool) -> None:
        for action in (
            self.action_new_doc,
            self.action_save,
            self.action_import,
            self.action_refresh,
            self.action_source_mode,
            self.action_reveal_project,
            self.action_config_tab,
        ):
            action.setEnabled(enabled)

    # ---------------------------------------------------------------- project
    def new_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择新项目目录")
        if not directory:
            return
        title, ok = QInputDialog.getText(self, "新建 Docusaurus 项目", "站点标题：", text="My Docs")
        if not ok:
            return
        try:
            project = scaffold_project(directory, title or "My Docs")
        except (ProjectError, OSError) as exc:
            QMessageBox.critical(self, "新建项目失败", str(exc))
            return
        self._load_project(project)
        self.statusBar().showMessage(f"已创建项目：{project.root}", 6000)

    def open_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择 Docusaurus 项目目录")
        if not directory:
            return
        try:
            project = DocusaurusProject(directory).load()
        except ProjectError as exc:
            QMessageBox.warning(self, "打开项目失败", str(exc))
            return
        self._load_project(project)

    def _load_project(self, project: DocusaurusProject) -> None:
        if not self._maybe_save():
            return
        self.project = project
        self.current_entry = None
        self.editor.clear_document()
        self.center_stack.setCurrentWidget(self.empty_page)
        self.front_matter_panel.set_document(None)
        self.config_panel.set_project(project)
        self.file_tree.set_tree(project.sidebar_tree())
        self._set_project_enabled(True)
        self.status_project.setText(str(project.root))
        self.setWindowTitle(f"{project.name} — Docueditor")
        self._settings.setValue("lastProject", str(project.root))
        if project.entries:
            self.open_document(project.entries[0].rel)

    @staticmethod
    def _tree_rel(rel: str) -> str:
        """Map an index document back to its folder node in the tree."""
        path = Path(rel)
        if path.stem.lower() == "index":
            parent = path.parent.as_posix()
            if parent not in ("", "."):
                return parent
        return rel

    def _require_project(self) -> DocusaurusProject | None:
        if self.project is None:
            QMessageBox.information(self, "没有项目", "请先打开或新建一个 Docusaurus 项目。")
            return None
        return self.project

    # -------------------------------------------------------------- documents
    def open_document(self, rel: str) -> None:
        project = self._require_project()
        if project is None:
            return
        if self.current_entry is not None and self.current_entry.rel == rel:
            self.center_stack.setCurrentWidget(self.editor)
            return
        if not self._maybe_save():
            self.file_tree.select(self._tree_rel(self.current_entry.rel if self.current_entry else rel))
            return
        entry = next((item for item in project.entries if item.rel == rel), None)
        if entry is None:
            entry = project.find(project.docs_dir / rel) if project.docs_dir else None
        if entry is None:
            QMessageBox.warning(self, "打开失败", f"找不到文档：{rel}")
            return
        self.current_entry = entry
        self.editor.load_document(entry.path, read_text(entry.path))
        self.center_stack.setCurrentWidget(self.editor)
        self.front_matter_panel.set_document(entry)
        self.action_source_mode.blockSignals(True)
        self.action_source_mode.setChecked(False)
        self.action_source_mode.blockSignals(False)
        self.editor.set_source_mode(False)
        self.setWindowTitle(f"{entry.rel} — {project.name} — Docueditor")
        self.file_tree.select(self._tree_rel(rel))
        self.statusBar().showMessage(f"已打开 {entry.rel}", 3000)

    def new_document(self, rel_dir: str) -> None:
        project = self._require_project()
        if project is None:
            return
        if not rel_dir:
            rel_dir = self.file_tree.selected_dir()
        title, ok = QInputDialog.getText(self, "新建文档", "文档标题：")
        if not ok or not title.strip():
            return
        if not self._maybe_save():
            return
        try:
            entry = project.create_doc(title.strip(), title=title.strip(), rel_dir=rel_dir)
        except (ProjectError, OSError) as exc:
            QMessageBox.critical(self, "新建文档失败", str(exc))
            return
        self._refresh_after_change()
        self.open_document(entry.rel)
        self.statusBar().showMessage(f"已创建 {entry.rel}", 4000)

    def rename_document(self, rel: str) -> None:
        project = self._require_project()
        if project is None:
            return
        entry = next((item for item in project.entries if item.rel == rel), None)
        if entry is None:
            return
        if self.current_entry is not None and self.current_entry.path == entry.path and not self._maybe_save():
            return
        new_name, ok = QInputDialog.getText(self, "重命名文档", "新文件名（不含扩展名）：", text=entry.path.stem)
        if not ok or not new_name.strip():
            return
        try:
            renamed = project.rename_doc(entry, new_name.strip())
        except OSError as exc:
            QMessageBox.critical(self, "重命名失败", str(exc))
            return
        was_current = self.current_entry is not None and self.current_entry.path == entry.path
        self._refresh_after_change()
        if was_current:
            self.open_document(renamed.rel)

    def delete_document(self, rel: str) -> None:
        project = self._require_project()
        if project is None:
            return
        entry = next((item for item in project.entries if item.rel == rel), None)
        if entry is None:
            return
        reply = QMessageBox.question(
            self,
            "删除文档",
            f"确定删除 {entry.rel} ？\n此操作不可撤销（建议使用版本控制）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            project.delete_doc(entry)
        except OSError as exc:
            QMessageBox.critical(self, "删除失败", str(exc))
            return
        if self.current_entry is not None and self.current_entry.path == entry.path:
            self.current_entry = None
            self.editor.clear_document()
            self.center_stack.setCurrentWidget(self.empty_page)
            self.front_matter_panel.set_document(None)
        self._refresh_after_change()
        self.statusBar().showMessage(f"已删除 {entry.rel}", 4000)

    def move_document(self, rel: str, delta: int) -> None:
        project = self._require_project()
        if project is None:
            return
        entry = next((item for item in project.entries if item.rel == rel), None)
        if entry is None:
            return
        if not self._maybe_save():
            return
        updated = project.move(entry, delta)
        self._refresh_after_change()
        self.file_tree.select(self._tree_rel(updated.rel))
        if self.current_entry is not None and self.current_entry.path == updated.path:
            self.current_entry = updated
            self.front_matter_panel.set_document(updated)
        self.statusBar().showMessage(f"{updated.rel} → sidebar_position {updated.position}", 4000)

    def handle_drop_move(
        self,
        source_kind: str,
        source_rel: str,
        target_parent: str,
        index: int,
        container_doc: str,
    ) -> None:
        """Handle a drag: move files and renumber document/folder positions."""
        project = self._require_project()
        if project is None or project.docs_dir is None:
            return
        source_entry = (
            next((item for item in project.entries if item.rel == source_rel), None)
            if source_kind == "doc"
            else None
        )
        source_path = (
            source_entry.path if source_entry is not None else project.docs_dir / source_rel
        )
        if not self._maybe_save():
            return
        try:
            if container_doc:
                target_entry = next(
                    (item for item in project.entries if item.rel == container_doc), None
                )
                if target_entry is None:
                    return
                was_target_current = (
                    self.current_entry is not None
                    and self.current_entry.path == target_entry.path
                )
                container = project.ensure_container(target_entry)
                if was_target_current:
                    self._refresh_after_change()
                    self.open_document(f"{container}/index.mdx")
                target_parent = container
                index = 10**9
            _, new_rel = project.move_node(source_kind, source_rel, target_parent, index)
        except (ProjectError, OSError) as exc:
            QMessageBox.critical(self, "移动失败", str(exc))
            self.refresh_tree()
            return
        was_current = (
            self.current_entry is not None
            and self.current_entry.path == source_path
        )
        self._refresh_after_change()
        self.file_tree.select(self._tree_rel(new_rel))
        if was_current:
            self.open_document(new_rel)
        elif self.current_entry is not None:
            refreshed = project.find(self.current_entry.path)
            if refreshed is not None:
                self.current_entry = refreshed
                self.front_matter_panel.set_document(refreshed)
        self.statusBar().showMessage(f"已移动 {new_rel}", 4000)

    def new_child_document(self, rel: str) -> None:
        """Create a child document, turning the parent into a folder if needed."""
        project = self._require_project()
        if project is None:
            return
        entry = next((item for item in project.entries if item.rel == rel), None)
        if entry is None:
            return
        if not self._maybe_save():
            return
        was_current = (
            self.current_entry is not None and self.current_entry.path == entry.path
        )
        try:
            container = project.ensure_container(entry)
        except (ProjectError, OSError) as exc:
            QMessageBox.critical(self, "创建子文档失败", str(exc))
            return
        self._refresh_after_change()
        if was_current:
            self.open_document(f"{container}/index.mdx")
        title, ok = QInputDialog.getText(self, "新建子文档", "文档标题：")
        if not ok or not title.strip():
            return
        try:
            child = project.create_doc(
                title.strip(), title=title.strip(), rel_dir=container
            )
        except (ProjectError, OSError) as exc:
            QMessageBox.critical(self, "创建子文档失败", str(exc))
            return
        self._refresh_after_change()
        self.open_document(child.rel)
        self.statusBar().showMessage(f"已创建 {child.rel}", 4000)

    def reveal_document(self, rel: str) -> None:
        project = self._require_project()
        if project is None or project.docs_dir is None:
            return
        path = project.docs_dir / rel
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def reveal_project(self) -> None:
        if self.project is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project.root)))

    def refresh_tree(self) -> None:
        if self.project is None:
            return
        self.project.scan()
        self.file_tree.set_tree(self.project.sidebar_tree())
        if self.current_entry is not None:
            self.file_tree.select(self._tree_rel(self.current_entry.rel))

    def _refresh_after_change(self) -> None:
        if self.project is None:
            return
        self.project.scan()
        self.file_tree.set_tree(self.project.sidebar_tree())

    # ------------------------------------------------------------------ save
    def _panel_overrides(self) -> dict[str, object]:
        if self.current_entry is None:
            return {}
        original = self.current_entry.front_matter.values
        panel = self.front_matter_panel.values()
        overrides: dict[str, object] = {}
        for key, value in panel.items():
            current = original.get(key)
            if key == "tags":
                current = list(current) if isinstance(current, (list, tuple)) else ([] if not current else current)
                value = list(value) if isinstance(value, (list, tuple)) else ([] if not value else value)
            if current != value:
                overrides[key] = value
        return overrides

    def save_current(self) -> bool:
        if self.project is None or self.current_entry is None:
            return True
        overrides = self._panel_overrides()
        if overrides:
            self.editor.set_front_matter_overrides(overrides)
        text = self.editor.current_text()
        try:
            entry = self.project.write_document(self.current_entry, text)
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return False
        self.current_entry = entry
        self.editor.set_modified(False)
        self.editor.clear_front_matter_overrides()
        self.front_matter_panel.set_document(entry)
        self.project.scan()
        self.file_tree.set_tree(self.project.sidebar_tree())
        self.file_tree.select(self._tree_rel(entry.rel))
        self.setWindowTitle(f"{entry.rel} — {self.project.name} — Docueditor")
        self.statusBar().showMessage(f"已保存 {entry.rel}", 3000)
        return True

    def _maybe_save(self) -> bool:
        if not self.editor.is_modified() or self.current_entry is None:
            return True
        reply = QMessageBox.warning(
            self,
            "未保存的修改",
            f"{self.current_entry.rel} 有未保存的修改，是否保存？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if reply == QMessageBox.StandardButton.Save:
            return self.save_current()
        return reply == QMessageBox.StandardButton.Discard

    def _on_modified(self, modified: bool) -> None:
        if self.project is None:
            return
        name = self.current_entry.rel if self.current_entry else self.project.name
        self.setWindowTitle(f"{'*' if modified else ''}{name} — {self.project.name} — Docueditor")

    # ------------------------------------------------------------ front matter
    def apply_front_matter(self, overrides: dict) -> None:
        if self.current_entry is None:
            return
        self.editor.set_front_matter_overrides(overrides)
        self.editor.text_edit.document().setModified(True)
        self.save_current()
        self.statusBar().showMessage("Front Matter 已应用", 3000)

    # --------------------------------------------------------------- import
    def import_content(self) -> None:
        project = self._require_project()
        if project is None:
            return
        if not self._maybe_save():
            return
        dialog = ImportDialog(project, self)
        dialog.imported.connect(self._on_imported)
        dialog.exec()

    def _on_imported(self, result) -> None:
        if self.project is None:
            return
        self.project.scan()
        self.file_tree.set_tree(self.project.sidebar_tree())
        message = f"导入完成：新建 {len(result.created)} 篇，覆盖 {len(result.overwritten)} 篇"
        self.statusBar().showMessage(message, 8000)
        QMessageBox.information(self, "导入完成", message)
        if self.project.entries:
            self.file_tree.select(self._tree_rel(self.project.entries[0].rel))

    def _on_config_saved(self, changed: list) -> None:
        if not changed:
            return
        self.statusBar().showMessage("已更新配置：" + "、".join(changed), 5000)

    # ------------------------------------------------------------------ misc
    def _toggle_source_mode(self, enabled: bool) -> None:
        if self.current_entry is None:
            self.action_source_mode.blockSignals(True)
            self.action_source_mode.setChecked(False)
            self.action_source_mode.blockSignals(False)
            return
        self.editor.set_source_mode(enabled)
        self.editor.mode_button.blockSignals(True)
        self.editor.mode_button.setChecked(enabled)
        self.editor.mode_button.setText("富文本模式" if enabled else "源码模式")
        self.editor.mode_button.blockSignals(False)

    def show_about(self) -> None:
        from PySide6 import __version__ as pyside_version
        from . import __version__

        QMessageBox.about(
            self,
            "关于 Docueditor",
            f"<h3>Docueditor {__version__}</h3>"
            "<p>面向 Docusaurus 文档站的所见即所得编辑器。</p>"
            "<p>支持导入 Novelwriter 与语雀内容，默认使用追加模式。</p>"
            f"<p>许可证：GPL-3.0-only<br/>PySide6 {pyside_version}</p>"
            "<p><b>这是一个 Vibe Coding 项目。</b></p>",
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._maybe_save():
            event.ignore()
            return
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("windowState", self.saveState())
        event.accept()

    def restore_window_state(self) -> None:
        geometry = self._settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self._settings.value("windowState")
        if state is not None:
            self.restoreState(state)
