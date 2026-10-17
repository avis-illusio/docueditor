import json

from docueditor import config_editor


CONFIG = """// keep this comment
const config = {
  title: 'My Site',
  tagline: 'A tagline',
  url: 'https://example.com',
  baseUrl: '/',
  organizationName: 'avis-illusio',
  projectName: 'my-site',
  presets: [
    ['classic', { docs: { path: 'docs' } }],
  ],
  themeConfig: {
    title: 'Nested title should be ignored',
  },
};

module.exports = config;
"""


def test_read_site_config(tmp_path):
    path = tmp_path / "docusaurus.config.js"
    path.write_text(CONFIG, encoding="utf-8")
    values = config_editor.read_site_config(path)
    assert values["title"] == "My Site"
    assert values["tagline"] == "A tagline"
    assert values["organizationName"] == "avis-illusio"


def test_update_site_config_preserves_structure(tmp_path):
    path = tmp_path / "docusaurus.config.js"
    path.write_text(CONFIG, encoding="utf-8")
    changed = config_editor.update_site_config(
        path, {"title": "New: Site", "tagline": "Changed"}
    )
    assert set(changed) == {"title", "tagline"}
    text = path.read_text(encoding="utf-8")
    assert "// keep this comment" in text
    assert "title: 'New: Site'" in text
    assert "Nested title should be ignored" in text
    assert "baseUrl: '/'" in text
    values = config_editor.read_site_config(path)
    assert values["title"] == "New: Site"
    assert values["tagline"] == "Changed"


def test_update_site_config_nochange(tmp_path):
    path = tmp_path / "docusaurus.config.js"
    path.write_text(CONFIG, encoding="utf-8")
    assert config_editor.update_site_config(path, {"title": "My Site"}) == []


def test_read_package_json(tmp_path):
    path = tmp_path / "package.json"
    path.write_text(json.dumps({"name": "site", "version": "1.0.0", "scripts": {}}), encoding="utf-8")
    values = config_editor.read_package_json(path)
    assert values == {"name": "site", "version": "1.0.0"}


def test_update_package_json(tmp_path):
    path = tmp_path / "package.json"
    path.write_text(json.dumps({"name": "site", "version": "1.0.0"}, indent=2), encoding="utf-8")
    changed = config_editor.update_package_json(path, {"version": "1.2.0", "description": "Docs"})
    assert set(changed) == {"version", "description"}
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == "1.2.0"
    assert data["description"] == "Docs"
