import gc
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCursor, QTextFormat  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docueditor.main_window import MainWindow  # noqa: E402
from docueditor.project import scaffold_project  # noqa: E402
from docueditor.widgets.editor import MarkdownEditor  # noqa: E402


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    config_home = tmp_path_factory.mktemp("config")
    os.environ["XDG_CONFIG_HOME"] = str(config_home)
    app = QApplication.instance() or QApplication([])
    yield app
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()
    gc.collect()
    app.processEvents()
    app.quit()


@pytest.fixture()
def project(tmp_path, qapp):
    return scaffold_project(tmp_path / "site", "Smoke")


def test_editor_roundtrip_preserves_mdx(qapp, tmp_path):
    editor = MarkdownEditor()
    path = tmp_path / "page.mdx"
    text = (
        "---\n"
        "title: Page\n"
        "sidebar_position: 2\n"
        "---\n"
        "\n"
        "# Page\n"
        "\n"
        "import Tabs from '@theme/Tabs';\n"
        "\n"
        "```python\n"
        "print('hi')\n"
        "```\n"
        "\n"
        "<Tabs>\n"
        "  <TabItem value=\"a\">A</TabItem>\n"
        "</Tabs>\n"
    )
    path.write_text(text, encoding="utf-8")
    editor.load_document(path, text)
    output = editor.current_text()
    assert "title: Page" in output
    assert "```python" in output
    assert "print('hi')" in output
    assert "<Tabs>" in output
    assert "import Tabs" in output
    editor.deleteLater()


def test_editor_source_mode_toggle(qapp, tmp_path):
    editor = MarkdownEditor()
    path = tmp_path / "page.md"
    text = "---\ntitle: Source\n---\n\n# Source\n"
    path.write_text(text, encoding="utf-8")
    editor.load_document(path, text)
    editor.set_source_mode(True)
    assert editor.source_mode
    editor.source_edit.setPlainText(text.replace("Source", "Source edited"))
    editor.set_source_mode(False)
    assert not editor.source_mode
    assert "Source edited" in editor.current_text()
    editor.deleteLater()


def test_main_window_loads_and_saves(qapp, project):
    window = MainWindow()
    window._load_project(project)
    assert window.current_entry is not None
    assert window.file_tree.tree.topLevelItemCount() > 0
    window.editor.text_edit.textCursor().insertText("正文内容")
    assert window.editor.is_modified()
    window.save_current()
    assert not window.editor.is_modified()
    saved = window.current_entry.path.read_text(encoding="utf-8")
    assert "正文内容" in saved
    window.deleteLater()


def test_main_window_create_document(qapp, project, monkeypatch):
    window = MainWindow()
    window._load_project(project)
    monkeypatch.setattr(
        "docueditor.main_window.NewDocumentDialog.ask",
        staticmethod(lambda *args, **kwargs: ("new-doc", "新文档标题")),
    )
    window.new_document("")
    assert window.current_entry is not None
    assert window.current_entry.rel == "new-doc.mdx"
    assert window.current_entry.title == "新文档标题"
    window.deleteLater()


def test_drop_handler_moves_document(qapp, project):
    window = MainWindow()
    window._load_project(project)
    entry = project.create_doc("second", title="Second")
    window._refresh_after_change()
    window.handle_drop_move("doc", entry.rel, "", 0, "")
    ordered = [item.title for item in project.entries]
    assert ordered[0] == "Second"
    assert window.current_entry is not None
    window.deleteLater()


def test_tree_drop_target_calculation(qapp, project):
    from PySide6.QtWidgets import QAbstractItemView

    window = MainWindow()
    window._load_project(project)
    a = project.create_doc("a", title="A")
    b = project.create_doc("b", title="B")
    c = project.create_doc("c", title="C")
    project.create_doc("x", title="X", rel_dir="guide")
    window._refresh_after_change()
    tree = window.file_tree.tree
    indicator = QAbstractItemView.DropIndicatorPosition

    def item_for(rel):
        return window.file_tree._find_item(rel)

    # Siblings at the root: intro, a, b, c.
    assert tree._drop_target("doc", c.rel, "", item_for(a.rel), indicator.AboveItem) == ("", 1, "")
    assert tree._drop_target("doc", a.rel, "", item_for(b.rel), indicator.BelowItem) == ("", 2, "")
    # Dropping on a folder appends inside it.
    assert tree._drop_target("doc", c.rel, "", item_for("guide"), indicator.OnItem) == ("guide", 1, "")
    # Dropping on a document turns that document into a folder.
    assert tree._drop_target("doc", c.rel, "", item_for(a.rel), indicator.OnItem) == ("", 0, a.rel)
    window.deleteLater()


def test_tree_labels_have_no_position_prefix(qapp, project):
    window = MainWindow()
    window._load_project(project)
    item = window.file_tree._find_item("intro.mdx")
    assert item is not None
    assert item.text(0) == "开始使用"
    window.deleteLater()


def test_drop_on_document_creates_container(qapp, project):
    target = project.create_doc("target", title="Target")
    source = project.create_doc("source", title="Source")
    window = MainWindow()
    window._load_project(project)
    window._refresh_after_change()
    window.handle_drop_move("doc", source.rel, "", 0, target.rel)
    assert (project.docs_dir / "target" / "index.mdx").is_file()
    assert (project.docs_dir / "target" / "source.mdx").is_file()
    assert not (project.docs_dir / "target.mdx").exists()
    assert window.current_entry is not None
    window.deleteLater()


def test_new_child_document_turns_parent_into_folder(qapp, project, monkeypatch):
    window = MainWindow()
    window._load_project(project)
    parent = project.create_doc("parent", title="Parent")
    window._refresh_after_change()
    monkeypatch.setattr(
        "docueditor.main_window.NewDocumentDialog.ask",
        staticmethod(lambda *args, **kwargs: ("child", "Child")),
    )
    window.new_child_document(parent.rel)
    assert (project.docs_dir / "parent" / "index.mdx").is_file()
    assert (project.docs_dir / "parent" / "child.mdx").is_file()
    window.deleteLater()


def test_container_node_opens_index(qapp, project):
    from docueditor.widgets.file_tree import ROLE_CONTAINER, ROLE_REL

    parent = project.create_doc("b", title="文档 B")
    project.ensure_container(parent)
    window = MainWindow()
    window._load_project(project)
    window._refresh_after_change()
    item = window.file_tree._find_item("b")
    assert item is not None
    assert item.data(0, ROLE_CONTAINER)
    opened = []
    window.file_tree.documentActivated.connect(opened.append)
    window.file_tree._activate(item)
    assert opened == ["b/index.mdx"]
    window.open_document("b/index.mdx")
    assert window.current_entry is not None
    assert window.current_entry.rel == "b/index.mdx"
    assert window.file_tree.tree.currentItem().data(0, ROLE_REL) == "b"
    window.deleteLater()


def test_input_method_menu_present(qapp, project):
    import sys

    if not sys.platform.startswith("linux"):
        pytest.skip("input method menu is Linux-only")
    window = MainWindow()
    window._load_project(project)
    assert set(window.im_actions) == {"auto", "fcitx5", "ibus", "none"}
    assert window.im_status_action.text().startswith("当前：")
    window.deleteLater()


def test_editor_table_quote_code_roundtrip(qapp, tmp_path):
    editor = MarkdownEditor()
    path = tmp_path / "page.mdx"
    text = (
        "---\n"
        "title: Page\n"
        "---\n"
        "\n"
        "> 引用内容\n"
        "\n"
        "| 名称 | 值 |\n"
        "| --- | --- |\n"
        "| 甲 | 1 |\n"
        "| 乙 | 2 |\n"
        "\n"
        "```python\n"
        "print(1)\n"
        "```\n"
        "\n"
        "- [ ] 任务\n"
        "- [x] 完成\n"
    )
    editor.load_document(path, text)
    output = editor.current_text()
    assert "> 引用内容" in output
    assert "| 名称 | 值 |" in output
    assert "| --- | --- |" in output
    assert "| 甲 | 1 |" in output
    assert "```python" in output
    assert "- [ ] 任务" in output
    assert "- [x] 完成" in output
    editor.deleteLater()


def test_editor_injects_front_matter_title_as_h1(qapp, tmp_path):
    editor = MarkdownEditor()
    path = tmp_path / "page.mdx"
    text = "---\ntitle: Hello\n---\n\nBody text\n"
    editor.load_document(path, text)
    block = editor.text_edit.document().firstBlock()
    assert block.text() == "Hello"
    assert block.blockFormat().headingLevel() == 1
    output = editor.current_text()
    assert output.count("# Hello") == 0
    assert "title: Hello" in output
    assert "Body text" in output
    editor.deleteLater()


def test_new_document_dialog_syncs_title_to_filename(qapp):
    from docueditor.widgets.new_document_dialog import NewDocumentDialog

    dialog = NewDocumentDialog(None, "guide")
    dialog.filename_edit.setText("my-page")
    assert dialog.title_edit.text() == "my page"
    dialog.title_edit.setText("自定义标题")
    dialog._title_edited("自定义标题")
    dialog.filename_edit.setText("other-page")
    assert dialog.title_edit.text() == "自定义标题"
    assert dialog.values() == ("other-page", "自定义标题")
    dialog.deleteLater()


def test_create_folder(qapp, project, monkeypatch):
    window = MainWindow()
    window._load_project(project)
    monkeypatch.setattr(
        "docueditor.main_window.NewFolderDialog.ask",
        staticmethod(lambda *args, **kwargs: ("guide", "指南")),
    )
    window.new_folder("")
    folder = project.docs_dir / "guide"
    assert folder.is_dir()
    data = __import__("json").loads(
        (folder / "_category_.json").read_text(encoding="utf-8")
    )
    assert data["label"] == "指南"
    assert window.file_tree._find_item("guide") is not None
    window.deleteLater()


def test_autoformat_markdown_input(qapp, tmp_path):
    editor = MarkdownEditor()
    editor.load_document(tmp_path / "x.mdx", "")
    editor.text_edit.setPlainText("---")
    cursor = editor.text_edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.text_edit.setTextCursor(cursor)
    assert editor._autoformat_hr()
    assert editor.current_text().strip() == "---"

    editor.text_edit.clear()
    editor.text_edit.setPlainText("# ")
    cursor = editor.text_edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.text_edit.setTextCursor(cursor)
    assert editor._autoformat_prefix()
    assert editor.text_edit.document().firstBlock().blockFormat().headingLevel() == 1
    editor.text_edit.textCursor().insertText("标题")
    assert editor.current_text().startswith("# 标题")

    editor.text_edit.clear()
    editor.text_edit.setPlainText("- [ ] ")
    cursor = editor.text_edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.text_edit.setTextCursor(cursor)
    assert editor._autoformat_prefix()
    assert editor.current_text().strip() == "- [ ]"
    editor.deleteLater()


def test_typography_applied(qapp, tmp_path):
    editor = MarkdownEditor()
    text = (
        "---\ntitle: Hello\n---\n\n"
        "## Section\n\n> quote\n\n"
        "```python\nprint(1)\n```\n\n"
        "| A | B |\n| --- | --- |\n| 1 | 2 |\n"
    )
    editor.load_document(tmp_path / "x.mdx", text)
    document = editor.text_edit.document()
    first = document.begin()
    assert first.blockFormat().headingLevel() == 1
    assert first.begin().fragment().charFormat().fontPointSize() == 26.0
    code_size = None
    block = first.next()
    while block.isValid():
        if block.blockFormat().property(
            QTextFormat.Property.BlockCodeLanguage
        ):
            code_size = block.begin().fragment().charFormat().fontPointSize()
            break
        block = block.next()
    assert code_size == 10.5
    assert editor._collect_tables()[0].format().border() == 1.0
    editor.deleteLater()


def test_new_folder_dialog_syncs_title_to_name(qapp):
    from docueditor.widgets.new_folder_dialog import NewFolderDialog

    dialog = NewFolderDialog(None, "docs")
    dialog.folder_edit.setText("guide")
    assert dialog.title_edit.text() == "guide"
    dialog.title_edit.setText("指南")
    dialog._title_edited("指南")
    dialog.folder_edit.setText("other")
    assert dialog.title_edit.text() == "指南"
    assert dialog.values() == ("other", "指南")
    dialog.deleteLater()


def test_hr_line_double_click_edit(qapp, tmp_path):
    editor = MarkdownEditor()
    editor.resize(700, 500)
    editor.show()
    editor.load_document(tmp_path / "x.mdx", "before\n\n---\n\nafter\n")
    qapp.processEvents()
    document = editor.text_edit.document()
    block = document.begin()
    hr_block = None
    while block.isValid():
        if block.blockFormat().property(
            QTextFormat.Property.BlockTrailingHorizontalRulerWidth
        ):
            hr_block = block
            break
        block = block.next()
    assert hr_block is not None
    point = editor.text_edit.cursorRect(QTextCursor(hr_block)).center()
    assert editor._begin_hr_edit(point)
    assert editor.text_edit.textCursor().block().text() == "---"
    cursor = editor.text_edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.text_edit.setTextCursor(cursor)
    editor._maybe_finish_hr_edit()
    assert document.findBlock(hr_block.position()).blockFormat().property(
        QTextFormat.Property.BlockTrailingHorizontalRulerWidth
    )
    assert "---" in editor.current_text()
    editor.deleteLater()


def test_table_editing_actions(qapp, tmp_path):
    editor = MarkdownEditor()
    editor.load_document(tmp_path / "x.mdx", "")
    cursor = editor.text_edit.textCursor()
    table = cursor.insertTable(2, 2)
    editor.text_edit.setTextCursor(cursor)
    editor._table_insert_row(1)
    assert table.rows() == 3
    editor._table_insert_column(1)
    assert table.columns() == 3
    editor._table_equal_width()
    assert len(table.format().columnWidthConstraints()) == 3
    editor._table_delete_row()
    assert table.rows() == 2
    # Table operations may move the cursor out; re-enter before deleting a column.
    editor.text_edit.setTextCursor(table.cellAt(0, 0).firstCursorPosition())
    editor._table_delete_column()
    assert table.columns() == 2
    editor.deleteLater()


@pytest.mark.skipif(
    sys.version_info < (3, 11), reason="PySide6 6.12/QImage teardown on 3.10"
)
def test_paste_image_copies_to_assets(qapp, tmp_path):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QImage

    docs = tmp_path / "site" / "docs"
    docs.mkdir(parents=True)
    document_path = docs / "guide" / "page.mdx"
    document_path.parent.mkdir()
    editor = MarkdownEditor()
    editor.set_project_context(docs)
    editor.load_document(document_path, "")
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(0xFF0000)
    mime = QMimeData()
    mime.setImageData(image)
    editor.text_edit.insertFromMimeData(mime)
    assets = list((docs / "assets").glob("*.png"))
    assert assets
    assert "![image](../assets/" in editor.current_text()
    editor.deleteLater()


@pytest.mark.skipif(
    sys.version_info < (3, 11), reason="PySide6 6.12/QTextTable teardown on 3.10"
)
def test_table_alignment_roundtrip(qapp, tmp_path):
    editor = MarkdownEditor()
    editor.resize(700, 500)
    editor.show()
    editor.load_document(
        tmp_path / "x.mdx",
        "| A | B |\n| :--- | ---: |\n| 1 | 2 |\n",
    )
    qapp.processEvents()
    assert "| --- | ---: |" in editor.current_text()
    table = editor._collect_tables()[0]
    editor.text_edit.setTextCursor(table.cellAt(0, 0).firstCursorPosition())
    editor._update_table_bar()
    assert editor.table_bar.isVisible()
    editor._table_set_alignment("center")
    assert "| :---: | ---: |" in editor.current_text()
    editor.deleteLater()
