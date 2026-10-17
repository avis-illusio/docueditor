import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
        "docueditor.main_window.QInputDialog.getText",
        staticmethod(lambda *args, **kwargs: ("新文档标题", True)),
    )
    window.new_document("")
    assert window.current_entry is not None
    assert "新文档标题" in window.current_entry.rel
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
    item = window.file_tree._find_item("intro.md")
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
    assert (project.docs_dir / "target" / "source.md").is_file()
    assert not (project.docs_dir / "target.md").exists()
    assert window.current_entry is not None
    window.deleteLater()


def test_new_child_document_turns_parent_into_folder(qapp, project, monkeypatch):
    window = MainWindow()
    window._load_project(project)
    parent = project.create_doc("parent", title="Parent")
    window._refresh_after_change()
    monkeypatch.setattr(
        "docueditor.main_window.QInputDialog.getText",
        staticmethod(lambda *args, **kwargs: ("Child", True)),
    )
    window.new_child_document(parent.rel)
    assert (project.docs_dir / "parent" / "index.mdx").is_file()
    assert (project.docs_dir / "parent" / "child.md").is_file()
    window.deleteLater()
