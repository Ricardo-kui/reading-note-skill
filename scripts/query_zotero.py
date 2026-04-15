#!/usr/bin/env python
"""
query_zotero.py — 从 Zotero SQLite 查询论文元数据
用法：python query_zotero.py "<title_keyword>"
输出：JSON，包含 item_key, attachment_key, citekey, title, authors, year, journal, doi, pdf_path

Gotcha：Zotero 运行时 sqlite 处于 WAL 写锁，必须先复制到临时文件再读取。
Gotcha：BBT citekey 存储在 extra 字段中，格式 "Citation Key: XxxYyyy2024"。

增量缓存策略：
  将 DB 副本缓存在 cache/zotero_cache.sqlite，同时记录源 DB 的 mtime。
  下次调用时对比 mtime，若 DB 未被修改则直接复用缓存，跳过 100MB 的复制开销。
  Zotero 只要有任何写入（新增/修改条目）都会更新 mtime，缓存即自动失效。
"""
import sys
import os
import sqlite3
import shutil
import json
import re

ZOTERO_DB = "C:/Users/40500/Zotero/zotero.sqlite"
ZOTERO_STORAGE = "C:/Users/40500/Zotero/storage"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
CACHE_DIR = os.path.join(SKILL_DIR, "cache")
CACHE_DB = os.path.join(CACHE_DIR, "zotero_cache.sqlite")
CACHE_MTIME_FILE = os.path.join(CACHE_DIR, "zotero_cache.mtime")


# ── 缓存管理 ──────────────────────────────────────────────────────────────────

def _get_source_mtime() -> float:
    """获取源 DB 的最新修改时间（取主文件和 WAL 文件的较大值）"""
    mtime = os.path.getmtime(ZOTERO_DB)
    wal = ZOTERO_DB + "-wal"
    if os.path.exists(wal):
        mtime = max(mtime, os.path.getmtime(wal))
    return mtime


def _read_cached_mtime() -> float:
    """读取上次缓存时记录的源 DB mtime，不存在返回 0"""
    try:
        with open(CACHE_MTIME_FILE, "r") as f:
            return float(f.read().strip())
    except Exception:
        return 0.0


def _write_cached_mtime(mtime: float) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_MTIME_FILE, "w") as f:
        f.write(str(mtime))


def get_db_path() -> str:
    """
    返回可安全读取的 DB 路径（优先复用缓存，mtime 变化时才重新复制）。
    调用方负责在使用完毕后不删除此路径——缓存文件会持久保留。
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    source_mtime = _get_source_mtime()
    cached_mtime = _read_cached_mtime()

    if os.path.exists(CACHE_DB) and source_mtime == cached_mtime:
        print(f"[zotero] 使用缓存 DB（mtime 未变）", file=sys.stderr)
        return CACHE_DB

    # 缓存失效：重新复制
    print(f"[zotero] DB 已更新，刷新缓存（{os.path.getsize(ZOTERO_DB)/1024/1024:.1f} MB）...", file=sys.stderr)
    tmp = CACHE_DB + ".tmp"
    shutil.copy2(ZOTERO_DB, tmp)
    for ext in ["-wal", "-shm"]:
        src = ZOTERO_DB + ext
        if os.path.exists(src):
            shutil.copy2(src, tmp + ext)

    # 原子替换（避免中途崩溃留下损坏的缓存）
    if os.path.exists(CACHE_DB):
        os.replace(tmp, CACHE_DB)
    else:
        os.rename(tmp, CACHE_DB)
    for ext in ["-wal", "-shm"]:
        t = tmp + ext
        c = CACHE_DB + ext
        if os.path.exists(t):
            os.replace(t, c)
        elif os.path.exists(c):
            os.unlink(c)

    _write_cached_mtime(source_mtime)
    print(f"[zotero] 缓存已刷新", file=sys.stderr)
    return CACHE_DB


# ── 辅助函数 ─────────────────────────────────────────────────────────────────

def resolve_attachment_path(raw_path: str, attachment_key: str) -> str:
    if not raw_path:
        return ""
    if raw_path.startswith("storage:"):
        filename = raw_path[len("storage:"):]
        return os.path.join(ZOTERO_STORAGE, attachment_key, filename).replace("\\", "/")
    return raw_path.replace("\\", "/")


def parse_citekey_from_extra(extra: str) -> str:
    if not extra:
        return ""
    match = re.search(r"Citation Key:\s*(\S+)", extra, re.IGNORECASE)
    return match.group(1) if match else ""


def generate_citekey(authors: list, year: str) -> str:
    if not authors:
        return f"Unknown{year}"
    first_last = re.sub(r"[^a-zA-Z]", "", authors[0].get("lastName", "") or "Unknown")
    if len(authors) == 1:
        return f"{first_last}{year}"
    elif len(authors) == 2:
        second = re.sub(r"[^a-zA-Z]", "", authors[1].get("lastName", "") or "")
        return f"{first_last}And{second}{year}"
    else:
        return f"{first_last}EtAl{year}"


# ── 主查询 ────────────────────────────────────────────────────────────────────

def query_by_title(keyword: str) -> dict:
    if not os.path.exists(ZOTERO_DB):
        return {"error": f"Zotero DB not found: {ZOTERO_DB}"}

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT i.itemID, i.key AS item_key, it.typeName
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            JOIN itemData id2 ON i.itemID = id2.itemID
            JOIN fields f ON id2.fieldID = f.fieldID
            JOIN itemDataValues idv ON id2.valueID = idv.valueID
            WHERE f.fieldName = 'title'
              AND idv.value LIKE ?
              AND it.typeName IN ('journalArticle','conferencePaper','preprint','thesis','bookSection','book')
            ORDER BY i.itemID DESC
            LIMIT 5
        """, (f"%{keyword}%",))
        rows = cur.fetchall()

        if not rows:
            return {"error": f"No items found matching: {keyword}"}

        item = rows[0]
        item_id = item["itemID"]
        item_key = item["item_key"]

        cur.execute("""
            SELECT f.fieldName, idv.value
            FROM itemData id2
            JOIN fields f ON id2.fieldID = f.fieldID
            JOIN itemDataValues idv ON id2.valueID = idv.valueID
            WHERE id2.itemID = ?
        """, (item_id,))
        fields = dict(cur.fetchall())

        cur.execute("""
            SELECT c.firstName, c.lastName, ct.creatorType
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
        """, (item_id,))
        authors = [
            {"firstName": r["firstName"] or "", "lastName": r["lastName"] or "", "type": r["creatorType"]}
            for r in cur.fetchall()
        ]

        cur.execute("""
            SELECT i2.key AS att_key, ia.path, ia.contentType
            FROM itemAttachments ia
            JOIN items i2 ON ia.itemID = i2.itemID
            WHERE ia.parentItemID = ?
              AND (ia.contentType = 'application/pdf' OR ia.path LIKE '%.pdf')
            ORDER BY i2.itemID DESC
            LIMIT 1
        """, (item_id,))
        att = cur.fetchone()
        attachment_key = att["att_key"] if att else ""
        pdf_path = resolve_attachment_path(att["path"] if att else "", attachment_key)

        extra = fields.get("extra", "")
        citekey = parse_citekey_from_extra(extra)
        year = (fields.get("date", "") or "")[:4]
        if not citekey:
            citekey = generate_citekey(authors, year)

        return {
            "item_key": item_key,
            "attachment_key": attachment_key,
            "citekey": citekey,
            "title": fields.get("title", ""),
            "abstract": fields.get("abstractNote", ""),
            "year": year,
            "journal": fields.get("publicationTitle", ""),
            "doi": fields.get("DOI", ""),
            "volume": fields.get("volume", ""),
            "issue": fields.get("issue", ""),
            "pages": fields.get("pages", ""),
            "authors": authors,
            "pdf_path": pdf_path,
            "zotero_select_uri": f"zotero://select/library/items/{item_key}",
            "zotero_pdf_uri": f"zotero://open-pdf/library/items/{attachment_key}" if attachment_key else "",
        }
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: query_zotero.py <title_keyword>", file=sys.stderr)
        sys.exit(1)
    result = query_by_title(sys.argv[1])
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(result, ensure_ascii=False, indent=2))
