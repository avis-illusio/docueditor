from docueditor import mdx_guard


def test_plain_markdown_is_untouched():
    text = "# Title\n\nSome **bold** text.\n\n- item\n"
    protected = mdx_guard.protect(text)
    assert protected.tokens == {}
    assert protected.text == text


def test_fenced_code_block_is_left_to_qt():
    text = "Intro\n\n```python\nprint('hi')\n```\n\nOutro\n"
    protected = mdx_guard.protect(text)
    assert protected.tokens == {}
    assert protected.text == text


def test_jsx_block_is_protected():
    text = "Before\n\n<Tabs>\n  <TabItem value=\"a\">A</TabItem>\n</Tabs>\n\nAfter\n"
    protected = mdx_guard.protect(text)
    assert len(protected.tokens) == 1
    assert "<Tabs>" not in protected.text
    assert protected.restore(protected.text) == text


def test_import_and_admonition_are_protected():
    text = (
        "import Tabs from '@theme/Tabs';\n\n"
        ":::note\n提示内容\n:::\n\n"
        "Body\n"
    )
    protected = mdx_guard.protect(text)
    assert len(protected.tokens) == 2
    assert "import Tabs" not in protected.text
    assert ":::note" not in protected.text
    assert protected.restore(protected.text) == text


def test_describe_tokens_labels():
    protected = mdx_guard.protect("<Tabs>\n  <TabItem value=\"a\">A</TabItem>\n</Tabs>\n")
    labels = mdx_guard.describe_tokens(protected)
    assert labels and "JSX" in labels[0]


def test_markdown_table_is_left_to_qt():
    text = "Before\n\n| 名称 | 值 |\n| --- | --- |\n| 甲 | 1 |\n\nAfter\n"
    protected = mdx_guard.protect(text)
    assert protected.tokens == {}
    assert protected.text == text


def test_code_fence_content_is_not_protected():
    text = "```mdx\n<Tabs>\nimport X from 'x';\n:::note\n```\n"
    protected = mdx_guard.protect(text)
    assert protected.tokens == {}
    assert protected.text == text
