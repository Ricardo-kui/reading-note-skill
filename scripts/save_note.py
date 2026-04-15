#!/usr/bin/env python
"""
save_note.py — 将笔记保存到 Obsidian vault，并追加结构化记忆日志
用法：python save_note.py <filename.md>  （内容从 stdin 读取）

改进：自动解析笔记 YAML frontmatter，提取 title / authors / year /
journal / citekey / tags，写入结构化记忆日志，支持后续语义匹配推荐关联笔记。
"""
import sys
import os
import re
import shutil
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
MEMORY_LOG = os.path.join(SKILL_DIR, "memory", "notes_log.md")

VAULT_PATH = "C:/Users/40500/OneDrive/Obsidian Vault"
LITERATURE_FOLDER = "literature"


# ── Frontmatter 解析 ──────────────────────────────────────────────────────────

def _extract_frontmatter(content: str) -> dict:
    """
    从 Markdown 内容中提取 YAML frontmatter 里的关键字段。
    只做轻量字符串解析，不引入 PyYAML 依赖。
    提取字段：title, year, journal, citekey, authors（列表）, tags（列表）
    """
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}

    fm_text = match.group(1)
    result: dict = {}

    # 单值字段
    for field in ("title", "year", "journal", "citekey"):
        m = re.search(rf'^{field}:\s*["\']?(.+?)["\']?\s*$', fm_text, re.MULTILINE)
        if m:
            result[field] = m.group(1).strip().strip('"').strip("'")

    # 列表字段（YAML block list: "  - value"）
    for field in ("authors", "tags"):
        # 找到 field: 后面跟着的缩进列表项
        block = re.search(rf'^{field}:\s*\n((?:[ \t]+-[^\n]+\n?)*)', fm_text, re.MULTILINE)
        if block:
            items = re.findall(r'^\s+-\s+"?([^"\n]+)"?', block.group(1), re.MULTILINE)
            result[field] = [i.strip() for i in items if i.strip()]

    return result


def _format_log_entry(filename: str, output_path: str, meta: dict) -> str:
    """
    生成结构化日志条目。格式示例：

    ### QianEtAl2024 · 2026-04-15
    - **title**: Better Safe Than Sorry: CEO Regulatory Focus and Workplace Safety
    - **authors**: Qian, Balaji, Crilly, Liu
    - **year**: 2024 · **journal**: Journal of Management
    - **topics**: CEO regulatory focus, workplace safety, upper echelons, stakeholder strategy
    - **file**: `qianetal2024-...md`
    - **path**: C:/Users/.../literature/qianetal2024-...md
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    citekey = meta.get("citekey", filename.replace(".md", ""))
    title = meta.get("title", "—")
    year = meta.get("year", "—")
    journal = meta.get("journal", "—")

    # authors: 取 lastName 部分
    raw_authors = meta.get("authors", [])
    if raw_authors:
        # 格式可能是 "Last, First" 或 "First Last"
        last_names = []
        for a in raw_authors[:4]:  # 最多显示 4 位
            parts = a.split(",")
            last_names.append(parts[0].strip())
        authors_str = ", ".join(last_names)
        if len(raw_authors) > 4:
            authors_str += " et al."
    else:
        authors_str = "—"

    # topics: 过滤掉通用标签，保留研究主题 tags
    generic = {"literature-note", "paper", "tool-note", "research-methodology", "writing-guide"}
    raw_tags = meta.get("tags", [])
    topics = [t for t in raw_tags if t.lower() not in generic]
    topics_str = ", ".join(topics) if topics else "—"

    lines = [
        f"\n### {citekey} · {date_str}",
        f"- **title**: {title}",
        f"- **authors**: {authors_str}",
        f"- **year**: {year} · **journal**: {journal}",
        f"- **topics**: {topics_str}",
        f"- **file**: `{filename}`",
        f"- **path**: {output_path}",
    ]
    return "\n".join(lines) + "\n"


# ── 主逻辑 ────────────────────────────────────────────────────────────────────

def save_note(filename: str, content: str) -> str:
    output_path = os.path.join(VAULT_PATH, LITERATURE_FOLDER, filename)
    output_path = os.path.normpath(output_path)

    # 备份已有文件
    if os.path.exists(output_path):
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = output_path.replace(".md", f".bak.{ts}.md")
        shutil.copy2(output_path, backup_path)
        print(f"[backup] {backup_path}")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[saved]  {output_path}")

    # 解析 frontmatter，写结构化记忆日志
    meta = _extract_frontmatter(content)
    log_entry = _format_log_entry(filename, output_path, meta)

    os.makedirs(os.path.dirname(MEMORY_LOG), exist_ok=True)
    with open(MEMORY_LOG, "a", encoding="utf-8") as f:
        f.write(log_entry)
    print(f"[logged] {MEMORY_LOG}")

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: save_note.py <filename.md>  (content from stdin)", file=sys.stderr)
        sys.exit(1)

    filename = sys.argv[1]
    content = sys.stdin.read()

    if not content.strip():
        print("ERROR: No content provided (stdin empty)", file=sys.stderr)
        sys.exit(1)

    save_note(filename, content)
