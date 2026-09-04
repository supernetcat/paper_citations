"""SQLite 存储：papers / citations 表 + 元信息。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .paths import runtime_root

OUT = runtime_root() / "outputs"
DB_PATH = OUT / "citations.db"


def connect(db_path: Path | str = DB_PATH, mode: str = "rwc"):
    """mode: rwc(默认可建) / ro(只读) / rw。"""
    uri = f"file:{Path(db_path).resolve()}?mode={mode}"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str = DB_PATH):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    c = conn.cursor()
    c.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS papers (
        paper_key TEXT PRIMARY KEY,
        label TEXT,
        doi TEXT, pmid TEXT, arxiv TEXT,
        title TEXT, journal TEXT, year INTEGER,
        source_input TEXT
    );
    CREATE TABLE IF NOT EXISTS citations (
        paper_key TEXT NOT NULL,
        source TEXT NOT NULL,
        status TEXT NOT NULL,
        cited_by INTEGER,
        counts_by_year_json TEXT,
        influential INTEGER,
        reference_count INTEGER,
        work_id TEXT,
        title TEXT, journal TEXT, issn TEXT, year INTEGER,
        extra_json TEXT,
        fetched_at TEXT,
        raw_file TEXT,
        PRIMARY KEY (paper_key, source)
    );
    CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
    """)
    conn.commit()
    return conn


def upsert_papers(rows: list[dict], db_path: Path | str = DB_PATH):
    conn = connect(db_path)
    try:
        c = conn.cursor()
        c.executemany("""
            INSERT OR REPLACE INTO papers
            (paper_key,label,doi,pmid,arxiv,title,journal,year,source_input)
            VALUES(:paper_key,:label,:doi,:pmid,:arxiv,:title,:journal,:year,:source_input)
        """, rows)
        conn.commit()
    finally:
        conn.close()


def upsert_citation(row: dict, db_path: Path | str = DB_PATH):
    conn = connect(db_path)
    try:
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO citations
            (paper_key,source,status,cited_by,counts_by_year_json,influential,
             reference_count,work_id,title,journal,issn,year,extra_json,fetched_at,raw_file)
            VALUES(:paper_key,:source,:status,:cited_by,:counts_by_year_json,:influential,
                   :reference_count,:work_id,:title,:journal,:issn,:year,:extra_json,:fetched_at,:raw_file)
        """, row)
        conn.commit()
    finally:
        conn.close()
