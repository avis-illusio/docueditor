from pathlib import Path

import pytest

from docueditor.project import DocusaurusProject, ProjectError, scaffold_project


@pytest.fixture()
def project(tmp_path: Path) -> DocusaurusProject:
    return scaffold_project(tmp_path / "site", "Test Docs")


def test_scaffold_creates_required_files(project: DocusaurusProject):
    assert project.config_path is not None
    assert project.docs_dir is not None
    assert (project.root / "sidebars.js").is_file()
    assert (project.root / "package.json").is_file()
    assert (project.docs_dir / "intro.md").is_file()
    assert project.entries


def test_scaffold_refuses_existing_project(project: DocusaurusProject):
    with pytest.raises(ProjectError):
        scaffold_project(project.root)


def test_create_doc_keeps_cjk_names_and_positions(project: DocusaurusProject):
    entry = project.create_doc("中文标题 测试", body="内容", title="中文标题 测试")
    assert entry.path.name == "中文标题-测试.md"
    assert entry.position == project.max_position()
    assert "sidebar_position" in entry.front_matter.values
    assert "内容" in entry.body
    names = [item.path.name for item in project.entries]
    assert len(names) == len(set(names))


def test_create_doc_deduplicates(project: DocusaurusProject):
    first = project.create_doc("guide", title="Guide")
    second = project.create_doc("guide", title="Guide")
    assert first.rel == "guide.md"
    assert second.rel == "guide-2.md"


def test_create_doc_in_subdirectory(project: DocusaurusProject):
    entry = project.create_doc("setup", title="Setup", rel_dir="getting-started")
    assert entry.rel == "getting-started/setup.md"
    assert entry.path.parent.name == "getting-started"


def test_save_and_write_document(project: DocusaurusProject):
    entry = project.create_doc("draft", title="Draft")
    saved = project.save_doc(entry, "# New body\n", {"title": "Renamed"})
    assert saved.title == "Renamed"
    assert "# New body" in saved.body
    text = saved.path.read_text(encoding="utf-8")
    assert "title: Renamed" in text
    replaced = project.write_document(saved, text.replace("New body", "Other body"))
    assert "Other body" in replaced.body


def test_title_falls_back_to_heading(project: DocusaurusProject):
    path = project.docs_dir / "no-frontmatter.md"
    path.write_text("# Heading Title\n\ntext\n", encoding="utf-8")
    project.scan()
    entry = next(item for item in project.entries if item.rel == "no-frontmatter.md")
    assert entry.title == "Heading Title"
    assert entry.position is None


def test_move_swaps_positions(project: DocusaurusProject):
    first = project.create_doc("one", title="One")
    second = project.create_doc("two", title="Two")
    assert first.position is not None and second.position is not None
    assert second.position > first.position
    moved = project.move(second, -1)
    assert moved.position == first.position
    refreshed_first = next(item for item in project.entries if item.path == first.path)
    assert refreshed_first.position == second.position


def test_delete_removes_empty_directory(project: DocusaurusProject):
    entry = project.create_doc("x", title="X", rel_dir="nested/deep")
    directory = entry.path.parent
    project.delete_doc(entry)
    assert not entry.path.exists()
    assert not directory.exists()


def test_rename_document(project: DocusaurusProject):
    entry = project.create_doc("old-name", title="Old")
    renamed = project.rename_doc(entry, "new-name")
    assert renamed.rel == "new-name.md"
    assert not entry.path.exists()


def test_config_summary(project: DocusaurusProject):
    summary = project.config_summary()
    assert summary["title"] == "Test Docs"
    assert summary["organizationName"] == "avis-illusio"
