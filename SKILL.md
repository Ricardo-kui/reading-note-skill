---
name: reading-notes
description: >
  当用户提供学术论文 PDF 路径（本地路径或 Zotero storage 路径）并要求做阅读笔记时触发。
  触发关键词：做文献笔记、读论文、阅读笔记、reading notes、take notes on、笔记这篇、读一下这篇。
  适用于 .pdf 文件，研究论文、工作论文、会议论文均可。
  不适用于：非学术 PDF（合同、报告）、网页文章、已有对应 Obsidian 笔记的论文（先检查 memory/notes_log.md）。
allowed-tools: Read Write Edit Bash
---

# Reading Notes

## 一句话定义

读 PDF → 按**阅读目的**选择框架分析 → 写段落体中英文笔记 → 存入 Obsidian → 写入记忆日志。

## 两种阅读模式

| 模式 | 目的 | 框架 | 触发词 |
|------|------|------|--------|
| **Researcher**（默认）| 评估研究的说服力：设计是否严谨、因果是否可信、贡献是否扎实 | AMJ Canvas 七模块 + 设计批判 | 默认，或"研究者模式"、"as a researcher" |
| **Writer** | 分析论文的写作策略：结构布局、引入方式、文献整合、结论写法 | Nelson 写作解剖框架 | "写作模式"、"as a writer"、"写法分析"、"怎么写的" |

**默认使用 Researcher 模式**。若用户未指定，先问一句："这篇想用研究者视角（评估设计与贡献）还是写作者视角（分析写作策略）？"——但若 PDF 属于方法工具类文档（如 AMJ Canvas Worksheet 自身），直接用 Researcher 模式不必询问。

## 快速工作流（每次执行顺序）

1. **确认阅读模式** — 未指定时简短询问（见上表）
2. **检查记忆** — 读 `memory/notes_log.md`，确认这篇论文是否已有笔记
3. **读 PDF** — `scripts/read_pdf.py <pdf_path>`
4. **查 Zotero 元数据** — `scripts/query_zotero.py "<title_keyword>"` 获取 item_key、attachment_key、citekey
5. **分析论文**
   - Researcher 模式：对照 `references/amj-canvas-questions.md` 七模块 + Nelson 设计批判问题
   - Writer 模式：对照 `assets/note_template_writer.md` 各节的分析维度
6. **生成笔记**
   - Researcher 模式：参照 `assets/note_template.md`
   - Writer 模式：参照 `assets/note_template_writer.md`
7. **保存笔记** — `scripts/save_note.py "<filename>" "<content>"` 写入 Obsidian，自动追加记忆日志

## ⚠️ Gotchas — 这套环境的实际坑

### Python 路径
**只能用这个 Python**：`C:/Users/40500/AppData/Local/Programs/Python/Python312/python.exe`
系统 PATH 里的 `python` / `python3` 命令在 bash 中找不到（exit code 127）。所有脚本调用都必须用完整路径。

### PDF 双引擎策略
`read_pdf.py` 有两套引擎，自动按顺序尝试：
1. **MarkItDown（首选）** — 快，无需 Java，适合普通文字型 PDF
2. **opendataloader-pdf（Fallback）** — 需要 Java 11+，适合复杂排版/多栏/表格/公式

**Fallback 自动触发条件**：MarkItDown 报错 或 输出字符数 < 200（内容过少视为失败）。
**强制使用 ODL**：`read_pdf.py <path> --force-odl`（用于已知 MarkItDown 效果差的 PDF）。
**opendataloader-pdf 的 Gotcha**：
- 需要 Java 11+，缺少 Java 时会报 `FileNotFoundError`，按提示安装 JDK：`https://adoptium.net/`
- 每次调用都会启动 JVM，比 MarkItDown 慢 5-10 秒，属正常现象
- 输出先写入临时目录，脚本读取后自动清理，不会留下垃圾文件

### Zotero SQLite 被锁
Zotero 运行时 `zotero.sqlite` 处于 WAL 模式写锁，直接 `sqlite3.connect()` 会报 `database is locked`。
**必须先复制到临时文件**再读取（`query_zotero.py` 已处理这个问题，不要跳过）。

### Better BibTeX citekey
BBT 的 `better-bibtex/` 目录是空的——说明 citekey 存储在 Zotero 主 sqlite 的 `extra` 字段里，格式为 `Citation Key: SomeKey2024`。`query_zotero.py` 会解析这个字段。如果 `extra` 字段也为空（很多老条目没有），按规则自动生成：第一作者姓 + 其他作者数量标记 + 年份，例如 `QianEtAl2024`、`EisenhardtAndSchoonhoven1996`。

### PDF 附件路径格式
Zotero 附件的 `path` 字段有两种格式：
- `storage:filename.pdf` — 在 `C:/Users/40500/Zotero/storage/<ATTACHMENT_KEY>/filename.pdf`
- 绝对路径（外部链接文件）— 直接用该路径
`query_zotero.py` 会自动转换。

### Obsidian 文件名规范
与现有笔记保持一致（见 `memory/notes_log.md` 中的已有文件名）：
`{第一作者姓小写}etal{year}-{标题关键词连字符小写}.md`
例：`qianetal2024-better-safe-than-sorry-ceo-regulatory-focus-and-workplace-safety.md`

### 笔记风格
**不要用 bullet list**。每个 section 写 2-4 段，中英文夹杂，核心术语/引用句保留英文，分析叙述用中文。参考 `references/note-style-guide.md`。

### 已有笔记冲突
如果 `memory/notes_log.md` 中已记录这篇论文，先告知用户，询问是覆盖还是追加。`save_note.py` 会自动备份旧文件（`.bak.时间戳.md`）。

## 输出验收标准

- [ ] YAML frontmatter 完整（含 zotero_select_uri，即使是空字符串也要保留 key）
- [ ] 七个 section 全部有实质内容（不是空的占位符）
- [ ] Quick View 是一段话，不是列表
- [ ] 有 `## Metadata Notes` 末尾块，含 Zotero 链接
- [ ] 文件已写入 `C:/Users/40500/OneDrive/Obsidian Vault/literature/`
- [ ] `memory/notes_log.md` 已追加新记录
