import zipfile
from pathlib import Path

import pytest

from docueditor.importers import base, novelwriter, yuque
from docueditor.project import scaffold_project


@pytest.fixture()
def project(tmp_path: Path):
    return scaffold_project(tmp_path / "site", "Docs")


def _make_novelwriter(root: Path) -> Path:
    nwd = root / "MyNovel.nwd"
    (nwd / "content").mkdir(parents=True)
    (nwd / "nwProject.nwx").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<novelWriter version="2.0" fileVersion="1.0">
  <project>
    <content>
      <item handle="aaa" order="1" parent="None" type="DOC" class="NOVEL" title="Chapter One"/>
      <item handle="bbb" order="2" parent="aaa" type="DOC" class="SCENE" title="Scene One"/>
      <item handle="ccc" order="3" parent="None" type="NOTE" class="NOTE" title="Notes"/>
    </content>
  </project>
</novelWriter>
""",
        encoding="utf-8",
    )
    (nwd / "content" / "aaa.txt").write_text(
        "# Chapter One\n\n% a private comment\n@char: Alice\n\nThe first chapter.\n",
        encoding="utf-8",
    )
    (nwd / "content" / "bbb.txt").write_text(
        "# Scene One\n\nA scene body.\n", encoding="utf-8"
    )
    return nwd


def test_novelwriter_project_import(tmp_path):
    nwd = _make_novelwriter(tmp_path)
    plan = novelwriter.load(nwd)
    assert plan.kind == "Novelwriter"
    assert [item.title for item in plan.items] == ["Chapter One", "Scene One"]
    assert plan.items[1].rel_dir == "chapter-one"
    assert "private comment" not in plan.items[0].body
    assert "@char" not in plan.items[0].body
    assert "The first chapter." in plan.items[0].body
    assert any("Notes" in warning for warning in plan.warnings)


def test_novelwriter_folder_import(tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "01-intro.md").write_text("# Intro\n\nHello\n", encoding="utf-8")
    (folder / "02-advanced.txt").write_text("Advanced body\n", encoding="utf-8")
    plan = novelwriter.load(folder)
    assert [item.title for item in plan.items] == ["Intro", "advanced"]
    assert plan.items[1].body == "Advanced body"


def test_novelwriter_single_file_sections(tmp_path):
    path = tmp_path / "book.md"
    path.write_text("# One\n\nfirst\n\n# Two\n\nsecond\n", encoding="utf-8")
    plan = novelwriter.load(path)
    assert [item.title for item in plan.items] == ["One", "Two"]
    assert "second" in plan.items[1].body


def test_yuque_html_table_conversion(tmp_path):
    folder = tmp_path / "yuque"
    folder.mkdir()
    (folder / "表格.md").write_text(
        "# 表格\n\n<p>前文 <strong>粗体</strong></p>\n"
        "<table><tr><th>名称</th><th>值</th></tr>"
        "<tr><td>甲</td><td>1</td></tr></table>\n",
        encoding="utf-8",
    )
    plan = yuque.load(folder)
    assert len(plan.items) == 1
    body = plan.items[0].body
    assert "**粗体**" in body
    assert "| 名称 | 值 |" in body
    assert "| 甲 | 1 |" in body


def test_yuque_zip_import(tmp_path):
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("知识库/01-入门.md", "# 入门\n\n内容一\n")
        zf.writestr("知识库/02-进阶.md", "# 进阶\n\n内容二\n")
        zf.writestr("__MACOSX/._junk", "x")
    plan = yuque.load(archive)
    assert [item.title for item in plan.items] == ["入门", "进阶"]
    assert all(item.rel_dir == "" for item in plan.items)


def test_yuque_single_file_sections(tmp_path):
    path = tmp_path / "all.md"
    path.write_text("# 甲\n\nA\n\n# 乙\n\nB\n", encoding="utf-8")
    plan = yuque.load(path)
    assert [item.title for item in plan.items] == ["甲", "乙"]


def test_append_mode_never_overwrites(project):
    existing = project.create_doc("guide", body="original")
    plan = base.ImportPlan(
        source=Path("x"),
        kind="测试",
        items=[base.ImportItem(title="Guide", body="imported")],
    )
    planned = base.plan_import(project, plan, base.APPEND)
    assert planned[0].rel == "guide-2.mdx"
    assert planned[0].action == "create"
    assert planned[0].position == project.max_position() + 1
    result = base.execute_import(project, plan, base.APPEND)
    assert result.created == ["guide-2.mdx"]
    assert "original" in existing.path.read_text(encoding="utf-8")
    new_file = project.docs_dir / "guide-2.mdx"
    assert "imported" in new_file.read_text(encoding="utf-8")


def test_replace_mode_backs_up(project):
    existing = project.create_doc("guide", body="original")
    plan = base.ImportPlan(
        source=Path("x"),
        kind="测试",
        items=[base.ImportItem(title="Guide", body="replacement")],
    )
    result = base.execute_import(project, plan, base.REPLACE)
    assert result.overwritten == ["guide.mdx"]
    assert result.backup_root is not None
    backup = result.backup_root / "guide.mdx"
    assert backup.is_file()
    assert "original" in backup.read_text(encoding="utf-8")
    assert "replacement" in (project.docs_dir / "guide.mdx").read_text(encoding="utf-8")


def test_imported_documents_have_front_matter(project):
    plan = base.ImportPlan(
        source=Path("x"),
        kind="测试",
        items=[base.ImportItem(title="设置", body="# 设置\n\n内容", rel_dir="guide")],
    )
    base.execute_import(project, plan)
    path = project.docs_dir / "guide" / "设置.mdx"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "title: 设置" in text
    assert "sidebar_position:" in text
