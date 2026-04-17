"""
dedup.py — SQLite增量去重模块
功能：记录已处理过的文章URL，每次运行只返回新增文章
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from config import DB_PATH

log = logging.getLogger(__name__)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_articles (
            url         TEXT PRIMARY KEY,
            title       TEXT,
            source      TEXT,
            first_seen  TEXT
        )
    """)
    conn.commit()
    return conn


def filter_new(articles: list[dict]) -> list[dict]:
    """
    传入文章列表，返回其中未见过的新文章。
    已见过的（URL已在数据库中）直接跳过。
    """
    if not articles:
        return []

    conn = _get_conn()
    urls = [a["url"] for a in articles if a.get("url")]

    if not urls:
        return articles

    placeholders = ",".join("?" * len(urls))
    seen = {
        row[0]
        for row in conn.execute(
            f"SELECT url FROM seen_articles WHERE url IN ({placeholders})", urls
        )
    }

    new_articles = [a for a in articles if a.get("url") and a["url"] not in seen]
    log.info(f"去重：输入{len(articles)}篇，已见过{len(seen)}篇，新增{len(new_articles)}篇")
    conn.close()
    return new_articles


def mark_seen(articles: list[dict]):
    """将文章列表写入数据库，标记为已处理。"""
    if not articles:
        return

    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.executemany(
        "INSERT OR IGNORE INTO seen_articles (url, title, source, first_seen) VALUES (?,?,?,?)",
        [
            (a.get("url", ""), a.get("title", ""), a.get("source", ""), now)
            for a in articles
            if a.get("url")
        ],
    )
    conn.commit()
    conn.close()
    log.info(f"已将{len(articles)}篇文章写入去重数据库")


def get_stats() -> dict:
    """返回数据库中的统计信息。"""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM seen_articles").fetchone()[0]
    by_source = conn.execute(
        "SELECT source, COUNT(*) FROM seen_articles GROUP BY source ORDER BY COUNT(*) DESC"
    ).fetchall()
    conn.close()
    return {"total": total, "by_source": dict(by_source)}
