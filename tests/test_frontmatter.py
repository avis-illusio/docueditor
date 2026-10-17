from docueditor import frontmatter


def test_split_basic_values():
    text = "---\ntitle: Hello\nsidebar_position: 3\ntags: [a, b]\ndraft: true\n---\n\n# Hi\n"
    fm = frontmatter.split(text)
    assert fm.has_header
    assert fm.values["title"] == "Hello"
    assert fm.values["sidebar_position"] == 3
    assert fm.values["tags"] == ["a", "b"]
    assert fm.values["draft"] is True
    assert fm.body == "\n# Hi\n"


def test_no_front_matter():
    fm = frontmatter.split("# Only body\n")
    assert not fm.has_header
    assert fm.values == {}
    assert fm.body == "# Only body\n"


def test_overrides_preserve_unknown_fields_and_comments():
    text = (
        "---\n"
        "# keep this comment\n"
        "title: Old\n"
        "custom:\n"
        "  nested: 1\n"
        "sidebar_position: 2\n"
        "---\n"
        "\n"
        "Body\n"
    )
    fm = frontmatter.split(text)
    out = fm.with_overrides({"title": "New: title", "sidebar_position": None})
    assert "# keep this comment" in out
    assert 'title: "New: title"' in out
    assert "sidebar_position" not in out
    assert "nested: 1" in out
    assert out.rstrip().endswith("Body")


def test_override_adds_keys_and_list():
    fm = frontmatter.split("Body only\n")
    out = fm.with_overrides({"title": "T", "tags": ["x", "y"], "sidebar_position": 4})
    assert out.startswith("---\n")
    assert "title: T" in out
    assert "tags:\n  - x\n  - y" in out
    assert "sidebar_position: 4" in out
    assert out.rstrip().endswith("Body only")


def test_quoted_and_nested_block_roundtrip():
    text = "---\ntitle: \"A \\\"quote\\\"\"\ntags:\n  - one\n  - two\n---\n\nbody\n"
    fm = frontmatter.split(text)
    assert fm.values["title"] == 'A "quote"'
    assert fm.values["tags"] == ["one", "two"]
    out = fm.with_overrides({"title": fm.values["title"]})
    assert out == text


def test_join_without_header():
    fm = frontmatter.FrontMatter(body="hello\n")
    assert frontmatter.join(fm) == "hello\n"
