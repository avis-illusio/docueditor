"""Document tree for a Docusaurus project."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..project import DocEntry

ROLE_TYPE = Qt.ItemDataRole.UserRole
ROLE_REL = Qt.ItemDataRole.UserRole + 1
ROLE_POSITION = Qt.ItemDataRole.UserRole + 2


class FileTree(QWidget):
    documentActivated = Signal(str)
    newDocumentRequested = Signal(str)
    renameRequested = Signal(str)
    deleteRequested = Signal(str)
    moveRequested = Signal(str, int)
    revealRequested = Signal(str)
    refreshRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[DocEntry] = []
        self._filter_text = ""

        self.search = QLineEdit()
        self.search.setPlaceholderText("筛选文档…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(14)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_menu)
        self.tree.itemActivated.connect(self._activate)
        self.tree.itemClicked.connect(self._activate)

        self.count_label = QLabel("0 篇文档")
        self.count_label.setObjectName("treeCount")

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.search, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.count_label)

    # ----------------------------------------------------------------- data
    def set_entries(self, entries: list[DocEntry]) -> None:
        expanded = self._expanded_paths()
        selected = self.selected_rel()
        self._entries = list(entries)
        self.tree.clear()
        directories: dict[str, QTreeWidgetItem] = {}
        for entry in entries:
            parts = entry.rel.split("/")
            parent = self.tree.invisibleRootItem()
            for depth, part in enumerate(parts[:-1]):
                key = "/".join(parts[: depth + 1])
                item = directories.get(key)
                if item is None:
                    item = QTreeWidgetItem([part])
                    item.setData(0, ROLE_TYPE, "dir")
                    item.setData(0, ROLE_REL, key)
                    item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                    item.setForeground(0, QColor("#8a8f98"))
                    parent.addChild(item)
                    directories[key] = item
                parent = item
            item = QTreeWidgetItem([self._label(entry)])
            item.setData(0, ROLE_TYPE, "doc")
            item.setData(0, ROLE_REL, entry.rel)
            item.setData(0, ROLE_POSITION, entry.position if entry.position is not None else -1)
            item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
            item.setToolTip(0, f"{entry.rel}\nsidebar_position: {entry.position if entry.position is not None else '未设置'}")
            parent.addChild(item)
        for path in expanded:
            item = self._find_dir(path)
            if item is not None:
                item.setExpanded(True)
        self.count_label.setText(f"{len(entries)} 篇文档")
        self._apply_filter(self._filter_text)
        if selected:
            self.select(selected)

    @staticmethod
    def _label(entry: DocEntry) -> str:
        title = entry.title or entry.path.stem
        if entry.position is not None:
            return f"{entry.position:02d} · {title}" if entry.position < 100 else f"{entry.position} · {title}"
        return f"— · {title}"

    def _expanded_paths(self) -> list[str]:
        result: list[str] = []
        stack = [self.tree.invisibleRootItem()]
        while stack:
            item = stack.pop()
            for index in range(item.childCount()):
                child = item.child(index)
                if child.data(0, ROLE_TYPE) == "dir" and child.isExpanded():
                    result.append(child.data(0, ROLE_REL))
                stack.append(child)
        return result

    def _find_dir(self, rel: str) -> QTreeWidgetItem | None:
        stack = [self.tree.invisibleRootItem()]
        while stack:
            item = stack.pop()
            for index in range(item.childCount()):
                child = item.child(index)
                if child.data(0, ROLE_TYPE) == "dir" and child.data(0, ROLE_REL) == rel:
                    return child
                stack.append(child)
        return None

    def _find_doc(self, rel: str) -> QTreeWidgetItem | None:
        stack = [self.tree.invisibleRootItem()]
        while stack:
            item = stack.pop()
            for index in range(item.childCount()):
                child = item.child(index)
                if child.data(0, ROLE_TYPE) == "doc" and child.data(0, ROLE_REL) == rel:
                    return child
                stack.append(child)
        return None

    # -------------------------------------------------------------- selection
    def current_item(self) -> QTreeWidgetItem | None:
        return self.tree.currentItem()

    def selected_rel(self) -> str | None:
        item = self.tree.currentItem()
        if item is None or item.data(0, ROLE_TYPE) != "doc":
            return None
        return item.data(0, ROLE_REL)

    def selected_dir(self) -> str:
        item = self.tree.currentItem()
        if item is None:
            return ""
        if item.data(0, ROLE_TYPE) == "dir":
            return item.data(0, ROLE_REL)
        rel = item.data(0, ROLE_REL) or ""
        return str(Path(rel).parent.as_posix()) if "/" in rel else ""

    def select(self, rel: str) -> None:
        item = self._find_doc(rel)
        if item is not None:
            self.tree.setCurrentItem(item)
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()

    # ----------------------------------------------------------------- filter
    def _apply_filter(self, text: str) -> None:
        self._filter_text = text
        needle = text.strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            if item.data(0, ROLE_TYPE) == "doc":
                haystack = f"{item.text(0)} {item.data(0, ROLE_REL)}".lower()
                visible = not needle or needle in haystack
                item.setHidden(not visible)
                return visible
            any_visible = False
            for index in range(item.childCount()):
                any_visible = visit(item.child(index)) or any_visible
            visible = any_visible or not needle
            item.setHidden(not visible)
            if needle and any_visible:
                item.setExpanded(True)
            return visible

        root = self.tree.invisibleRootItem()
        for index in range(root.childCount()):
            visit(root.child(index))

    # ------------------------------------------------------------------- menu
    def _show_menu(self, point) -> None:
        item = self.tree.itemAt(point)
        menu = QMenu(self)
        if item is None:
            action = QAction("新建文档…", menu)
            action.triggered.connect(lambda: self.newDocumentRequested.emit(""))
            menu.addAction(action)
        elif item.data(0, ROLE_TYPE) == "doc":
            rel = item.data(0, ROLE_REL)
            for label, slot in (
                ("打开", lambda: self.documentActivated.emit(rel)),
                ("上移", lambda: self.moveRequested.emit(rel, -1)),
                ("下移", lambda: self.moveRequested.emit(rel, 1)),
                ("重命名…", lambda: self.renameRequested.emit(rel)),
                ("在文件管理器中显示", lambda: self.revealRequested.emit(rel)),
            ):
                action = QAction(label, menu)
                action.triggered.connect(slot)
                menu.addAction(action)
            menu.addSeparator()
            delete = QAction("删除…", menu)
            delete.triggered.connect(lambda: self.deleteRequested.emit(rel))
            menu.addAction(delete)
        else:
            rel_dir = item.data(0, ROLE_REL)
            action = QAction("在此新建文档…", menu)
            action.triggered.connect(lambda: self.newDocumentRequested.emit(rel_dir))
            menu.addAction(action)
            action = QAction("展开全部", menu)
            action.triggered.connect(lambda: self._expand(item))
            menu.addAction(action)
        menu.addSeparator()
        refresh = QAction("刷新", menu)
        refresh.triggered.connect(self.refreshRequested.emit)
        menu.addAction(refresh)
        menu.exec(self.tree.viewport().mapToGlobal(point))

    def _expand(self, item: QTreeWidgetItem) -> None:
        item.setExpanded(True)
        for index in range(item.childCount()):
            self._expand(item.child(index))

    def _activate(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        if item is not None and item.data(0, ROLE_TYPE) == "doc":
            self.documentActivated.emit(item.data(0, ROLE_REL))
