"""Sidebar tree for a Docusaurus project.

The tree mirrors the generated sidebar: documents and ``_category_.json``
folders share one position space, so a folder can be dragged between levels
just like a document.  Dropping never moves items inside Qt; it only reports
the intended target and the project model performs the file move and
renumbers positions.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QLineEdit,
    QMenu,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..project import TreeNode

ROLE_TYPE = Qt.ItemDataRole.UserRole
ROLE_REL = Qt.ItemDataRole.UserRole + 1
ROLE_POSITION = Qt.ItemDataRole.UserRole + 2
ROLE_PARENT = Qt.ItemDataRole.UserRole + 3
ROLE_CONTAINER = Qt.ItemDataRole.UserRole + 4
ROLE_INDEX = Qt.ItemDataRole.UserRole + 5


class _DocTree(QTreeWidget):
    """Internal-move tree that reports drops instead of moving items."""

    dropRequested = Signal(str, str, str, int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nodes: list[TreeNode] = []
        self._drag_kind: str | None = None
        self._drag_rel: str | None = None
        self._drag_parent: str = ""
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAutoExpandDelay(350)

    def set_tree_nodes(self, nodes: list[TreeNode]) -> None:
        self._nodes = list(nodes)

    def _children_of(self, parent_rel: str) -> list[TreeNode]:
        if not parent_rel:
            return self._nodes
        stack = list(self._nodes)
        while stack:
            node = stack.pop()
            if node.kind == "dir":
                if node.rel == parent_rel:
                    return node.children
                stack.extend(node.children)
        return []

    def startDrag(self, supported_actions: Qt.DropAction) -> None:  # noqa: N802
        item = self.currentItem()
        if item is not None and item.data(0, ROLE_TYPE) in {"doc", "dir"}:
            self._drag_kind = item.data(0, ROLE_TYPE)
            self._drag_rel = item.data(0, ROLE_REL)
            self._drag_parent = item.data(0, ROLE_PARENT) or ""
        else:
            self._drag_kind = None
            self._drag_rel = None
            self._drag_parent = ""
        super().startDrag(supported_actions)
        self._drag_kind = None
        self._drag_rel = None
        self._drag_parent = ""

    def dropEvent(self, event) -> None:  # noqa: N802
        if (
            event.source() is not self
            or self._drag_kind is None
            or self._drag_rel is None
        ):
            event.ignore()
            return
        target_item = self.itemAt(event.position().toPoint())
        indicator = self.dropIndicatorPosition()
        target = self._drop_target(
            self._drag_kind,
            self._drag_rel,
            self._drag_parent,
            target_item,
            indicator,
        )
        # The project model moves files and renumbers positions; the tree is
        # rebuilt from disk afterwards.
        event.ignore()
        if target is not None:
            parent_rel, index, container_doc = target
            self.dropRequested.emit(
                self._drag_kind,
                self._drag_rel,
                parent_rel,
                index,
                container_doc,
            )

    def _drop_target(
        self,
        source_kind: str,
        source_rel: str,
        source_parent: str,
        target_item: QTreeWidgetItem | None,
        indicator: QAbstractItemView.DropIndicatorPosition,
    ) -> tuple[str, int, str] | None:
        if target_item is None:
            return ("", len(self._nodes), "")
        kind = target_item.data(0, ROLE_TYPE)
        target_rel = target_item.data(0, ROLE_REL)
        target_parent = target_item.data(0, ROLE_PARENT) or ""
        if kind == "doc" and indicator == QAbstractItemView.DropIndicatorPosition.OnItem:
            # Dropping onto a document turns it into a folder (Yuque-style).
            return ("", 0, target_rel)
        if kind == "dir" and indicator == QAbstractItemView.DropIndicatorPosition.OnItem:
            return (target_rel, len(self._children_of(target_rel)), "")
        siblings = self._children_of(target_parent)
        index = next(
            (
                position
                for position, node in enumerate(siblings)
                if node.kind == kind and node.rel == target_rel
            ),
            None,
        )
        if index is None:
            return None
        if indicator == QAbstractItemView.DropIndicatorPosition.BelowItem:
            index += 1
        if source_parent == target_parent:
            source_index = next(
                (
                    position
                    for position, node in enumerate(siblings)
                    if node.kind == source_kind and node.rel == source_rel
                ),
                None,
            )
            if source_index is not None and source_index < index:
                index -= 1
        return (target_parent, index, "")


class FileTree(QWidget):
    documentActivated = Signal(str)
    newDocumentRequested = Signal(str)
    newChildDocumentRequested = Signal(str)
    renameRequested = Signal(str)
    deleteRequested = Signal(str)
    moveRequested = Signal(str, int)
    dropRequested = Signal(str, str, str, int, str)
    revealRequested = Signal(str)
    refreshRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nodes: list[TreeNode] = []
        self._filter_text = ""

        self.search = QLineEdit()
        self.search.setPlaceholderText("筛选文档…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)

        self.tree = _DocTree()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(14)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_menu)
        self.tree.itemActivated.connect(self._activate)
        self.tree.itemClicked.connect(self._activate)
        self.tree.dropRequested.connect(self.dropRequested)

        self.count_label = QLabel("0 篇文档")
        self.count_label.setObjectName("treeCount")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(self.search)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.count_label)

    # ----------------------------------------------------------------- data
    def set_tree(self, nodes: list[TreeNode]) -> None:
        expanded = self._expanded_paths()
        selected = self.selected_rel() or self.selected_dir()
        self._nodes = list(nodes)
        self.tree.set_tree_nodes(nodes)
        self.tree.clear()
        self._build(self.tree.invisibleRootItem(), nodes, "")
        for path in expanded:
            item = self._find_item(path)
            if item is not None:
                item.setExpanded(True)
        if not expanded and self.tree.topLevelItemCount() == 1:
            self.tree.topLevelItem(0).setExpanded(True)
        documents = self._count_docs(nodes)
        folders = self._count_dirs(nodes)
        self.count_label.setText(f"{documents} 篇文档 · {folders} 个目录")
        self._apply_filter(self._filter_text)
        if selected:
            self.select(selected)

    def _build(
        self,
        parent_item: QTreeWidgetItem,
        nodes: list[TreeNode],
        parent_rel: str,
    ) -> None:
        for node in nodes:
            item = QTreeWidgetItem([node.label])
            item.setData(0, ROLE_TYPE, node.kind)
            item.setData(0, ROLE_REL, node.rel)
            item.setData(0, ROLE_PARENT, parent_rel)
            item.setData(
                0, ROLE_POSITION, node.position if node.position is not None else -1
            )
            item.setData(0, ROLE_CONTAINER, node.container)
            item.setData(0, ROLE_INDEX, node.index_rel or "")
            if node.kind == "dir" and not node.container:
                item.setIcon(
                    0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
                )
                item.setForeground(0, QColor("#8a8f98"))
                item.setToolTip(
                    0,
                    f"{node.rel}\nposition: "
                    f"{node.position if node.position is not None else '未设置'}",
                )
            else:
                item.setIcon(
                    0, self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
                )
                if node.container:
                    item.setToolTip(
                        0,
                        f"{node.rel}\n页面: {node.index_rel}\nposition: "
                        f"{node.position if node.position is not None else '未设置'}",
                    )
                else:
                    item.setToolTip(
                        0,
                        f"{node.rel}\nsidebar_position: "
                        f"{node.position if node.position is not None else '未设置'}",
                    )
            parent_item.addChild(item)
            if node.kind == "dir":
                self._build(item, node.children, node.rel)

    @staticmethod
    def _count_docs(nodes: list[TreeNode]) -> int:
        total = 0
        for node in nodes:
            if node.kind == "doc":
                total += 1
            else:
                total += FileTree._count_docs(node.children)
                if node.container:
                    total += 1
        return total

    @staticmethod
    def _count_dirs(nodes: list[TreeNode]) -> int:
        total = 0
        for node in nodes:
            if node.kind == "dir":
                total += 1 + FileTree._count_dirs(node.children)
        return total

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

    def _find_item(self, rel: str) -> QTreeWidgetItem | None:
        stack = [self.tree.invisibleRootItem()]
        while stack:
            item = stack.pop()
            for index in range(item.childCount()):
                child = item.child(index)
                if child.data(0, ROLE_REL) == rel:
                    return child
                stack.append(child)
        return None

    # -------------------------------------------------------------- selection
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
            return item.data(0, ROLE_REL) or ""
        return item.data(0, ROLE_PARENT) or ""

    def select(self, rel: str) -> None:
        item = self._find_item(rel)
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
            if item.data(0, ROLE_TYPE) not in {"doc", "dir"}:
                return False
            haystack = f"{item.text(0)} {item.data(0, ROLE_REL)}".lower()
            is_dir = item.data(0, ROLE_TYPE) == "dir"
            if is_dir:
                any_child = False
                for index in range(item.childCount()):
                    any_child = visit(item.child(index)) or any_child
                visible = any_child or not needle or needle in haystack
                if needle and any_child:
                    item.setExpanded(True)
            else:
                visible = not needle or needle in haystack
            item.setHidden(not visible)
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
        elif item.data(0, ROLE_TYPE) == "doc" or item.data(0, ROLE_CONTAINER):
            container = bool(item.data(0, ROLE_CONTAINER))
            rel = item.data(0, ROLE_REL)
            page_rel = item.data(0, ROLE_INDEX) if container else rel
            for label, slot in (
                ("打开", lambda: self.documentActivated.emit(page_rel)),
                ("在此文档下新建子文档…", lambda: self.newChildDocumentRequested.emit(page_rel)),
                ("上移", lambda: self.moveRequested.emit(rel, -1)),
                ("下移", lambda: self.moveRequested.emit(rel, 1)),
                ("重命名…", lambda: self.renameRequested.emit(rel)),
                ("在文件管理器中显示", lambda: self.revealRequested.emit(page_rel)),
            ):
                action = QAction(label, menu)
                action.triggered.connect(slot)
                menu.addAction(action)
            if container:
                action = QAction("展开全部", menu)
                action.triggered.connect(lambda: self._expand(item))
                menu.addAction(action)
            else:
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
        if item is None:
            return
        if item.data(0, ROLE_TYPE) == "doc":
            self.documentActivated.emit(item.data(0, ROLE_REL))
        elif item.data(0, ROLE_CONTAINER):
            page_rel = item.data(0, ROLE_INDEX)
            if page_rel:
                self.documentActivated.emit(page_rel)
