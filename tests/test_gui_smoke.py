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
