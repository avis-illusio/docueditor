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
    window.handle_drop_move(entry.rel, "", 0)
    ordered = [item.title for item in project.entries]
    assert ordered[0] == "Second"
    assert window.current_entry is not None
    window.deleteLater()


def test_tree_drop_target_calculation(qapp, project):
    from PySide6.QtWidgets import QAbstractItemView

    from docueditor.widgets.file_tree import ROLE_TYPE

    window = MainWindow()
    window._load_project(project)
    a = project.create_doc("a", title="A")
    b = project.create_doc("b", title="B")
    c = project.create_doc("c", title="C")
    window._refresh_after_change()
    tree = window.file_tree.tree

    def item_for(rel):
        window.file_tree.select(rel)
        return tree.currentItem()

    indicator = QAbstractItemView.DropIndicatorPosition
    # Drag C above A -> index 1 (siblings are intro, a, b, c).
    assert tree._drop_target(c.rel, item_for(a.rel), indicator.AboveItem) == ("", 1)
    # Drag A below B -> [intro, b, a, c].
    assert tree._drop_target(a.rel, item_for(b.rel), indicator.BelowItem) == ("", 2)
    # Drop C onto a directory -> append inside it.
    folder = project.create_doc("x", title="X", rel_dir="guide")
    window._refresh_after_change()
    dir_item = None
    stack = [tree.invisibleRootItem()]
    while stack:
        item = stack.pop()
        for index in range(item.childCount()):
            child = item.child(index)
            if child.data(0, ROLE_TYPE) == "dir":
                dir_item = child
            stack.append(child)
    assert dir_item is not None
    assert tree._drop_target(c.rel, dir_item, indicator.OnItem) == ("guide", 1)
    window.deleteLater()
