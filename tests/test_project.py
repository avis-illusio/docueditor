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
    assert (project.docs_dir / "intro.mdx").is_file()
    assert project.entries


def test_scaffold_refuses_existing_project(project: DocusaurusProject):
    with pytest.raises(ProjectError):
        scaffold_project(project.root)


def test_create_doc_keeps_cjk_names_and_positions(project: DocusaurusProject):
    entry = project.create_doc("中文标题 测试", body="内容", title="中文标题 测试")
    assert entry.path.name == "中文标题-测试.mdx"
    assert entry.position == project.max_position()
    assert "sidebar_position" in entry.front_matter.values
    assert "内容" in entry.body
    names = [item.path.name for item in project.entries]
    assert len(names) == len(set(names))


def test_create_doc_deduplicates(project: DocusaurusProject):
    first = project.create_doc("guide", title="Guide")
    second = project.create_doc("guide", title="Guide")
    assert first.rel == "guide.mdx"
    assert second.rel == "guide-2.mdx"


def test_create_doc_in_subdirectory(project: DocusaurusProject):
    entry = project.create_doc("setup", title="Setup", rel_dir="getting-started")
    assert entry.rel == "getting-started/setup.mdx"
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
    assert renamed.rel == "new-name.mdx"
    assert not entry.path.exists()


def test_config_summary(project: DocusaurusProject):
    summary = project.config_summary()
    assert summary["title"] == "Test Docs"
    assert summary["organizationName"] == "avis-illusio"


def test_move_document_within_directory_renumbers(project):
    a = project.create_doc("a", title="A")
    b = project.create_doc("b", title="B")
    c = project.create_doc("c", title="C")
    assert [entry.title for entry in project.entries] == ["开始使用", "A", "B", "C"]
    moved = project.move_document(c, "", 0)
    assert moved.position == 1
    assert [entry.title for entry in project.entries] == ["C", "开始使用", "A", "B"]
    assert [entry.position for entry in project.entries] == [1, 2, 3, 4]


def test_move_document_index_adjustment(project):
    a = project.create_doc("a", title="A", rel_dir="sec")
    b = project.create_doc("b", title="B", rel_dir="sec")
    c = project.create_doc("c", title="C", rel_dir="sec")
    # The tree passes the insertion index after the source has been removed.
    moved = project.move_document(a, "sec", 1)
    titles = [entry.title for entry in project.entries if entry.rel.startswith("sec/")]
    assert titles == ["B", "A", "C"]
    assert moved.position == 2


def test_move_document_across_directories(project):
    entry = project.create_doc("setup", title="Setup")
    moved = project.move_document(entry, "guide", 0)
    assert moved.rel == "guide/setup.mdx"
    assert moved.path.is_file()
    assert moved.position == 1
    assert not (project.docs_dir / "setup.mdx").exists()
    # The source directory is renumbered too.
    assert [item.position for item in project.entries if "/" not in item.rel] == [1]


def test_move_document_to_root(project):
    entry = project.create_doc("deep", title="Deep", rel_dir="guide")
    moved = project.move_document(entry, "", project.max_position())
    assert moved.rel == "deep.mdx"
    assert moved.path.is_file()
    assert not (project.docs_dir / "guide" / "deep.mdx").exists()
    assert [item.rel for item in project.entries] == ["intro.mdx", "deep.mdx"]


import json


def test_sidebar_tree_mixes_folders_and_documents(project):
    intro = next(item for item in project.entries if item.rel == "intro.mdx")
    project.set_position(intro, 5)
    guide = project.create_doc("x", title="X", rel_dir="guide")
    category = project.docs_dir / "guide" / "_category_.json"
    category.write_text(
        json.dumps({"label": "Guide", "position": 1}), encoding="utf-8"
    )
    later = project.create_doc("later", title="Later")
    project.scan()
    tree = project.sidebar_tree()
    assert [node.label for node in tree] == ["Guide", "开始使用", "Later"]
    assert tree[0].kind == "dir"
    assert tree[0].children[0].rel == guide.rel
    assert tree[0].position == 1
    assert later.position == 6


def test_move_folder_into_another_folder(project):
    first = project.create_doc("x", title="X", rel_dir="alpha")
    second = project.create_doc("y", title="Y", rel_dir="beta")
    project.scan()
    kind, new_rel = project.move_node("dir", "alpha", "beta", 1)
    assert kind == "dir"
    assert new_rel == "beta/alpha"
    assert (project.docs_dir / "beta" / "alpha" / "x.mdx").is_file()
    assert not (project.docs_dir / "alpha").exists()
    beta = next(node for node in project.sidebar_tree() if node.rel == "beta")
    assert beta.position == 2
    assert [node.label for node in beta.children] == ["Y", "alpha"]


def test_move_folder_rewrites_category_links(project):
    project.create_doc("x", title="X", rel_dir="guide")
    category = project.docs_dir / "guide" / "_category_.json"
    category.write_text(
        json.dumps(
            {
                "label": "Guide",
                "position": 1,
                "link": {"type": "doc", "id": "guide/x"},
            }
        ),
        encoding="utf-8",
    )
    project.scan()
    _, new_rel = project.move_node("dir", "guide", "section", 0)
    assert new_rel == "section/guide"
    data = json.loads(
        (project.docs_dir / "section" / "guide" / "_category_.json").read_text(
            encoding="utf-8"
        )
    )
    assert data["link"]["id"] == "section/guide/x"


def test_ensure_container_creates_index_and_category(project):
    entry = project.create_doc("widgets", title="Widgets", body="Hello")
    original_position = entry.position
    container = project.ensure_container(entry)
    assert container == "widgets"
    index = project.docs_dir / "widgets" / "index.mdx"
    assert index.is_file()
    assert not entry.path.exists()
    text = index.read_text(encoding="utf-8")
    assert "slug: /widgets" in text
    assert "sidebar_position: 1" in text
    data = json.loads(
        (project.docs_dir / "widgets" / "_category_.json").read_text(encoding="utf-8")
    )
    assert data["label"] == "Widgets"
    assert data["position"] == original_position
    assert data["link"] == {"type": "doc", "id": "widgets/index"}
    child = project.create_doc("child", title="Child", rel_dir=container)
    assert child.position == 2


def test_ensure_container_is_idempotent(project):
    entry = project.create_doc("guide", title="Guide")
    container = project.ensure_container(entry)
    index = project.find(project.docs_dir / "guide" / "index.mdx")
    assert index is not None
    assert project.ensure_container(index) == container


def test_move_index_document_updates_category_link(project):
    entry = project.create_doc("guide", title="Guide")
    container = project.ensure_container(entry)
    index_rel = f"{container}/index.mdx"
    project.move_node("doc", index_rel, "other", 0)
    data = json.loads(
        (project.docs_dir / "guide" / "_category_.json").read_text(encoding="utf-8")
    )
    assert data["link"]["id"] == "other/index"


def test_sidebar_tree_marks_document_container(project):
    parent = project.create_doc("b", title="文档 B")
    child = project.create_doc("a", title="文档 A")
    container = project.ensure_container(parent)
    project.move_node("doc", child.rel, container, 0)
    node = next(n for n in project.sidebar_tree() if n.rel == container)
    assert node.kind == "dir"
    assert node.container is True
    assert node.index_rel == "b/index.mdx"
    assert node.label == "文档 B"
    assert [item.label for item in node.children] == ["文档 A"]
    assert node.children[0].rel == "b/a.mdx"


def test_move_inside_container_keeps_index_first(project):
    parent = project.create_doc("b", title="B")
    project.ensure_container(parent)
    project.create_doc("a", title="A", rel_dir="b")
    project.create_doc("c", title="C", rel_dir="b")
    project.move_node("doc", "b/a.mdx", "b", 1)
    node = next(n for n in project.sidebar_tree() if n.rel == "b")
    assert [item.label for item in node.children] == ["C", "A"]
    positions = {
        entry.rel: entry.position
        for entry in project.entries
        if entry.rel.startswith("b/")
    }
    assert positions == {"b/index.mdx": 1, "b/c.mdx": 2, "b/a.mdx": 3}
