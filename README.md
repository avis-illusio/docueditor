# Docueditor

> [!IMPORTANT]
> **这是一个 Vibe Coding 项目。** 本项目从第一行代码到 README 都由人类与 AI 结对“凭感觉”写就（vibe coding），
> 以可运行、可读、可改为主，不追求企业级工程规范。请把它当作一个乐于助人但不保证不出错的编辑器来使用，
> 重要文档请先备份，或使用版本控制（git）兜底。

Docueditor 是一个面向 [Docusaurus](https://docusaurus.io/) 文档站的桌面编辑器。它让你在编辑
Docusaurus 的 Markdown / MDX 文档时获得 **WYSIWYG（所见即所得）** 的舒适感：新建文件、富文本编辑、
删除文件、调整侧边栏顺序、修改项目配置，全都在一个窗口里完成。

同时，它能导入 [Novelwriter](https://novelwriter.io/) 与 [语雀](https://www.yuque.com/) 的内容，
按照原有顺序生成 Docusaurus 文档，**默认使用“增加模式”（append）而不是“替换模式”** —— 导入只会在
你的文档站里追加新页面，不会悄悄覆盖已有内容。

- 语言：Python 3.10+
- GUI：PySide6（Qt 6）
- 许可证：**GPL-3.0-only**

---

## 功能

| 能力 | 说明 |
| --- | --- |
| 打开 / 新建项目 | 识别 `docusaurus.config.{js,ts,mjs,cjs}`，自动定位 `docs/` 目录与 `sidebars.*` |
| 所见即所得编辑 | 标题、粗体、斜体、删除线、列表、任务列表、引用、行内代码、链接、图片、表格、代码块、分隔线都在编辑器里直接呈现和编辑 |
| 完整 Markdown | 常用 CommonMark + GitHub 方言语法均可编辑；表格使用自定义序列化，避免 Qt 导出丢列 |
| 源码模式 | `Ctrl+E` 在富文本与 Markdown 源码之间切换，适合处理复杂 MDX |
| MDX 安全保护 | `import` / `export`、JSX 组件块、`:::` 指令、HTML 注释以占位符形式保留，保存时原样写回 |
| Front Matter 面板 | 可视化编辑 `title`、`id`、`sidebar_position`、`tags`、`draft` 等常用字段；`title` 会自动作为文章开头的一级标题显示 |
| 新建文档 | 文件名与标题分开填写；标题默认跟随文件名，手动修改后不再联动 |
| 文件管理 | 新建文档、新建文件夹、重命名、删除文档；新建默认 `.mdx`，自动维护唯一文件名与同层序号 |
| 拖拽排序 | 文档与目录共用一套 position 排序，均可拖动；拖到文档中心会把它变成“文档节点 + 子页面” |
| 目录与子文档 | 文档转容器后树中仍显示为文档（可点击打开 index），普通文件夹显示为文件夹；`_category_.json` 记录 position 与页面链接 |
| 直链页面 | 转换时 index.mdx 自动写入原路径的 slug，`_category_.json` 的 link 指向它，URL 保持不变 |
| 清爽文件树 | 不再显示 `01 ·` 序号前缀，顺序完全由 position 决定 |
| 中文输入法 | Linux 下自动识别 fcitx5 / IBus，设置 `QT_IM_MODULE` 并加载系统 Qt6 插件；`编辑 → 输入法` 可切换 |
| 项目配置 | 直接修改 `docusaurus.config.js` 中的 `title`、`tagline`、`url`、`baseUrl`、组织与项目名等字段（文本级安全改写，保留注释与格式） |
| 导入 Novelwriter | 解析 `.nwd` 项目（`nwProject.nwx` + `content/`），按书目顺序与层级生成文档树 |
| 导入语雀 | 支持语雀导出的 Markdown 文件夹 / ZIP / 单文件合集，转换表格、图片与语雀专有标签 |
| 导入预览 | 导入前先“预演”，列出将创建的文件、冲突处理与序号分配，确认后再落盘 |
| 追加 / 替换模式 | 默认追加：冲突文件自动加后缀，序号接在现有文档之后；替换模式需显式选择并二次确认 |
| 新建项目 | 一键生成可运行的 Docusaurus 站点骨架（config、sidebars、docs、package.json） |

### Markdown 语法

| 语法 | 支持 |
| --- | --- |
| 标题 / 段落 | 富文本直接编辑；Front Matter `title` 作为开头 H1 |
| 粗体 / 斜体 / 删除线 / 行内代码 | 工具栏与快捷键 |
| 有序 / 无序 / 任务列表 | 工具栏；任务列表保留 `[ ]` / `[x]` 状态 |
| 引用 `>` | 工具栏「引用」切换，加载与保存均保留 |
| 链接 / 图片 | 工具栏插入；图片保留 alt 与地址 |
| 代码块 | 可编辑，保留语言标记（如 `python`） |
| 表格 | 可编辑；保存时按文档中的表格结构重新生成 Markdown，避免 Qt 导出丢列 |
| 水平分隔线 | 工具栏「分隔线」 |

脚注、数学公式、复杂 HTML/MDX 等扩展语法仍建议切到源码模式（`Ctrl+E`）。

![Docueditor 主界面](docs/screenshot.png)

## 安装

### 预编译包（推荐）

从 [Releases](https://github.com/avis-illusio/docueditor/releases) 下载对应平台的文件：

| 平台 | 文件 | 使用 |
| --- | --- | --- |
| Windows | `Docueditor-<版本>-windows-x86_64.exe` | 双击运行 |
| Linux（AppImage） | `docueditor-<版本>-x86_64.AppImage` | `chmod +x` 后运行 |
| Linux（单文件） | `docueditor-<版本>-x86_64` | `chmod +x` 后运行 |
| Debian / Ubuntu | `docueditor_<版本>_amd64.deb` | `sudo apt install ./docueditor_*.deb` |
| Fedora / RHEL | `docueditor-<版本>-1.x86_64.rpm` | `sudo dnf install ./docueditor-*.rpm` |
| Arch Linux | `docueditor-<版本>-1-x86_64.pkg.tar.zst` | `sudo pacman -U ./docueditor-*.pkg.tar.zst` |
| macOS（Apple Silicon） | `Docueditor-<版本>-macOS-arm64.dmg` | 拖入「应用程序」 |

- Linux 包依赖 `libxkbcommon`、`libEGL`、`xcb-util-cursor` 等，主流桌面环境已自带；
- macOS 包为 Apple Silicon（arm64），未签名/未公证；首次打开请右键 → 打开，或执行 `xattr -dr com.apple.quarantine /Applications/Docueditor.app`。Intel Mac 请从源码安装；
- Windows 触发 SmartScreen 时选择「更多信息 → 仍要运行」。

### 从源码安装

需要 Python 3.10 或更高版本。

```bash
git clone https://github.com/avis-illusio/docueditor.git
cd docueditor
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

只装依赖不安装项目本身：

```bash
pip install PySide6
```

## 运行

```bash
docueditor                       # 启动后从菜单打开或新建 Docusaurus 项目
docueditor /path/to/docusaurus-site
```

也可以：

```bash
python -m docueditor /path/to/docusaurus-site
```

### 中文输入法（Linux）

Docueditor 启动时会：

1. 尊重已有的 `QT_IM_MODULE`；未设置时按运行中的 fcitx5 / IBus 自动选择（fcitx5 优先）；
2. 从系统 Qt6 插件目录生成一个只含输入法插件的临时 overlay，并加入 `QT_PLUGIN_PATH`，让 PySide6 自带的 Qt 也能加载系统的 fcitx5 插件；
3. 在 `编辑 → 输入法` 显示当前模块与插件状态，可切换自动 / fcitx5 / IBus / 关闭（重启生效）。

需要安装 Qt6 输入法前端（Qt 插件由系统提供，应用不内置）：

- Arch：`sudo pacman -S fcitx5-qt`
- Debian / Ubuntu：`sudo apt install fcitx5-frontend-qt6`
- Fedora：`sudo dnf install fcitx5-qt`
- IBus：PySide6 已内置 IBus 插件，一般无需额外安装

命令行覆盖：

```bash
docueditor --im fcitx5 /path/to/docusaurus-site
DOCUEDITOR_IM=ibus docueditor
docueditor --im none            # 关闭输入法模块
```

AppImage 与 PyInstaller 包不内置输入法插件，运行时从系统加载，请先安装上面的 fcitx5-qt。

如果打包版提示 fcitx5 插件加载失败（`CXXABI_1.3.15 not found`），说明包内自带的
libstdc++ 比系统插件旧。v0.5.1 起启动器会自动预加载系统 libstdc++；旧版本可以临时这样启动：

```bash
LD_PRELOAD=/usr/lib/libstdc++.so.6 docueditor
```

诊断当前状态：

```bash
docueditor --im-status
```

会打印 Qt/PySide6 版本、会话类型、`QT_IM_MODULE`、插件路径以及 fcitx5/IBus 插件是否找到。

## 基本用法

1. **打开项目**：`文件 → 打开 Docusaurus 项目`，选择包含 `docusaurus.config.js` 的目录。
2. **编辑文档**：左侧文件树选择文档，中间区域直接编辑。工具栏分两行，提供标题、粗斜体、删除线、行内代码、列表、任务列表、引用、链接、代码块、表格、图片与分隔线。
3. **保存**：`Ctrl+S`。Front Matter 与正文一起写回；新建文档默认使用 `.mdx`。Front Matter 的 `title` 会在文章最开头以一级标题显示，保存时不会在正文里重复写入。
4. **新建文档**：文件名输入框在上、标题在下；标题默认跟随文件名，手动改过标题后不再自动同步。
5. **调整顺序**：直接拖动文档或目录到目标位置；拖到文档中心会把它变成“可展开的文档节点”，子页面缩进显示，父节点仍可点击打开（语雀式）。`sidebar_position` 与 `_category_.json` 的 `position` 会自动重排。
6. **创建子文档**：右键父文档 →「在此文档下新建子文档…」。底层自动变成 `同名目录/index.mdx` + `_category_.json`，但树里仍显示为原来的文档；普通文件夹仍显示为文件夹。
7. **新建文件夹**：右键目录或空白处 →「新建文件夹…」，会在同层创建 `_category_.json`（label + position）。
8. **导入**：`文件 → 导入…`，选择 Novelwriter 或语雀，先看预览，再点“执行导入”（生成 `.mdx`）。
9. **输入法（Linux）**：启动时自动识别 fcitx5/IBus；也可在 `编辑 → 输入法` 切换，或用 `--im fcitx5` / `DOCUEDITOR_IM` 覆盖（重启生效）。

### 目录索引页（index.mdx）

当目录内存在 `index.md` / `index.mdx` / `README.md` / 与目录同名的文档时，Docueditor 会在打开项目或刷新时自动补全该目录的 `_category_.json`：

```json
{
  "label": "sidebar_label 或 title",
  "position": 3,
  "link": {
    "type": "doc",
    "id": "guide/index"
  }
}
```

- `label` 优先取文档的 `sidebar_label` front matter，其次 `title`；
- `link.id` 是文档 id（默认是相对 docs 的路径去扩展名，如 `guide/index`）；
- 已有 `link` 不会被覆盖；已有 `label` / `position` 也保留；
- 目录索引文档的 URL 通过 `slug` 保持 `/<目录>` 直链。

`sidebar_position` 与 `_category_.json` 的 `position` **只在同一目录层级内排序**：`A.mdx`、`B.mdx`、`C/` 共用一组序号，`C/AC.mdx`、`C/BC.mdx`、`D/AC.mdx` 各自在自己的目录内从 1 开始；拖拽重排只重写当前层级的 `1..n`。

## 导入说明

### Novelwriter

支持两种输入：

- **`.nwd` 项目目录**：读取 `nwProject.nwx` 中的 `content` 树，按 `order` 排序，读取 `content/*.txt|*.md` 正文。
- **普通文件夹**：按文件名自然排序，每个文本文件作为一篇文档，首行 `#` 标题作为文档标题。

转换规则：

- novelwriter 的书目层级（Chapter / Scene）映射为 Docusaurus 的子目录 + 文档；
- 正文中的 `%` 注释行、`@pov`、`@location` 等标签行会被清理；
- `#` / `##` 标题保留在正文中，文档自身的 `title` 取自 novelwriter 的项目标题。

### 语雀

支持三种输入：

- 语雀导出的 **Markdown 文件夹**（保留目录层级）；
- 语雀导出的 **ZIP**；
- 语雀导出的 **单文件 Markdown 合集**（按一级标题切分为多篇）。

转换规则：

- 语雀的 HTML `<table>` 转为 Markdown 表格；
- `<img src="...">` 转为 Markdown 图片，`<br>` 转为换行；
- 去除 `<card>`、`<p style=...>` 等语雀专有标签；
- 文件名前的数字序号（如 `01-xxx.md`）用于确定顺序，并从最终文件名中移除；
- 文档顺序写入 `sidebar_position`。

### 追加模式（默认）

- 目标目录中已存在的同名文件 **不会被覆盖**，而是生成 `name-2.md`、`name-3.md`；
- 新文档的 `sidebar_position` 从现有最大值往后排；
- 导入完成后弹出报告：创建了哪些文件、跳过了哪些、有哪些警告；
- 替换模式必须在导入对话框中显式切换，并勾选确认框，执行时会先备份原文件为 `.bak`。

## 项目结构

```
docueditor/
├── src/docueditor/
│   ├── app.py                 # 应用入口
│   ├── main_window.py         # 主窗口
│   ├── frontmatter.py         # YAML front matter 解析与序列化
│   ├── project.py             # Docusaurus 项目模型（文档树、序号、增删改）
│   ├── config_editor.py       # docusaurus.config.js 文本级安全改写
│   ├── mdx_guard.py           # MDX / JSX / 指令块占位符保护
│   ├── importers/
│   │   ├── base.py            # 导入计划、冲突处理、落盘
│   │   ├── novelwriter.py     # Novelwriter 导入
│   │   └── yuque.py           # 语雀导入
│   └── widgets/
│       ├── editor.py          # WYSIWYG 编辑器与工具栏
│       ├── file_tree.py       # 文档树
│       ├── frontmatter_panel.py
│       ├── config_panel.py
│       └── import_dialog.py
└── tests/                     # pytest：逻辑层 + 离屏 GUI 冒烟测试
```

## 开发

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

GUI 冒烟测试在无显示环境下运行：

```bash
QT_QPA_PLATFORM=offscreen pytest -q
```

## 打包

Linux 本地一键构建（需要 PyInstaller、curl；脚本会自动下载 appimagetool 与 nfpm）：

```bash
pip install pyinstaller
bash packaging/build_linux.sh
```

产物：

```
dist/docueditor-<版本>-x86_64              # 单文件 ELF
dist/docueditor-<版本>-x86_64.AppImage
dist/docueditor_<版本>_amd64.deb
dist/docueditor-<版本>-1.x86_64.rpm
dist/docueditor-<版本>-1-x86_64.pkg.tar.zst
```

跨平台构建由 GitHub Actions 完成（`.github/workflows/build-packages.yml`）：
推送 `v*` 标签或手动触发时，自动构建 Windows `.exe`、Linux 可执行文件/AppImage/deb/rpm/pkg.tar.zst、
macOS arm64 `.dmg`，并附加到对应的 GitHub Release。

打包配置位于 [`packaging/`](packaging/)：PyInstaller spec、desktop 文件、nfpm 配置与图标。

## 已知限制

- 表格会保留行列与文本，但列对齐（`:---:`）会统一导出为 `---`；
- 引用块中的软换行在富文本里会合并成一个段落，保存为一行引用；
- 复杂的 MDX 表达式（如嵌套 JSX 内的 Markdown）建议用源码模式编辑；
- 项目配置改写是“文本级”的：它能处理常见的 `key: 'value'` 写法并保留注释，但无法理解任意 JS 表达式；
- 不内置 Docusaurus 预览服务器，可在项目目录自行运行 `npm run start`。
- 目录移动后会更新 `_category_.json` 里的 `link.id`；文档 front matter 中手写的绝对 `slug` 不会自动改写。
- 文档转容器时，磁盘上的目录名仍是原文件名（如 `guide/`），树和 Docusaurus 侧边栏显示的是文档标题 / `_category_.json` 的 label；这样不会破坏已有 URL。
- 新建文档默认 `.mdx`；已有的 `.md` 文档照常编辑。
- 中文输入法依赖系统 Qt6 插件（fcitx5-qt）；应用负责设置模块与插件路径，不内置输入法引擎。
- 目录的重命名与删除暂未提供（可先在文件管理器中操作）。

## 路线图

- [x] 内置 Markdown 源码模式切换
- [x] 代码块 / 表格 / JSX 往返保护
- [ ] 图片粘贴自动保存到 `static/img/` 并改写链接
- [ ] 文档内链接与锚点检查
- [ ] 导入 Notion / Obsidian
- [x] 多平台安装包（Windows / Linux / macOS）
- [x] 目录/文档混合排序、目录拖拽、文档转容器
- [ ] 目录重命名与删除
- [ ] 多标签页编辑

## 许可证

本项目以 **GPL-3.0-only** 发布，详见 [LICENSE](LICENSE)。

```
Docueditor — a WYSIWYG editor for Docusaurus documentation.
Copyright (C) 2025 avis-illusio

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License only.
```

本项目使用 PySide6（Qt for Python），遵循其 LGPL/GPL 授权条款。
