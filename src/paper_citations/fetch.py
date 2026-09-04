"""抓取编排：读输入清单 → 多源并发拉取 → 写 DB + 原始响应缓存。支持断点续跑。"""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .http import get_json
from .ids import paper_key, norm_arxiv, norm_doi, norm_pmid
from .paths import runtime_root
from .sources import FETCHERS
from .store import DB_PATH, init_db, upsert_citation, upsert_papers

ROOT = runtime_root()
RAW_DIR = ROOT / "outputs" / "cache" / "raw"
DEFAULT_INPUT = ROOT / "data" / "input" / "papers.csv"

_SAN = re.compile(r"[^0-9A-Za-z._-]")


def _safe(key: str) -> str:
    return _SAN.sub("_", key)[:80]


def load_input(path: Path | str = DEFAULT_INPUT):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            doi = norm_doi(r.get("doi"))
            pmid = norm_pmid(r.get("pmid"))
            arxiv = norm_arxiv(r.get("arxiv"))
            title = (r.get("title") or "").strip() or None
            journal = (r.get("journal") or "").strip() or None
            year = None
            if (r.get("year") or "").strip().isdigit():
                year = int(r["year"])
            key = paper_key(doi, pmid, arxiv, title)
            rows.append({"paper_key": key, "label": (r.get("label") or "").strip() or key,
                         "doi": doi, "pmid": pmid, "arxiv": arxiv,
                         "title": title, "journal": journal, "year": year,
                         "source_input": (r.get("source_input") or "csv").strip()})
    return rows


def _done_sources(conn, refresh: bool):
    """返回已“完成”无需重拉 (paper_key, source) 集合。"""
    if refresh:
        return set()
    cur = conn.execute(
        "SELECT paper_key, source FROM citations "
        "WHERE status IN ('ok','ok_titlesearch','not_found','no_identifier')")
    return {(r["paper_key"], r["source"]) for r in cur.fetchall()}


def _task(pk_row, source, refresh, db_path=DB_PATH):
    """单 (论文, 源) 拉取并入库。返回记录 dict。"""
    p = pk_row
    fn = FETCHERS[source]
    rec = fn(doi=p["doi"], pmid=p["pmid"], arxiv=p["arxiv"], title=p["title"])
    rec["paper_key"] = p["paper_key"]
    rec["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    raw_file = None
    if rec["status"] in ("ok", "ok_titlesearch"):
        raw_file = f"{source}/{_safe(p['paper_key'])}.json"
        out = RAW_DIR / raw_file
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")

    dbrow = {
        "paper_key": p["paper_key"], "source": source, "status": rec["status"],
        "cited_by": rec["cited_by"],
        "counts_by_year_json": json.dumps(rec["counts_by_year"], ensure_ascii=False)
        if rec["counts_by_year"] else None,
        "influential": rec["influential"], "reference_count": rec["reference_count"],
        "work_id": rec["work_id"], "title": rec["title"], "journal": rec["journal"],
        "issn": rec["issn"], "year": rec["year"],
        "extra_json": json.dumps(rec["extra"], ensure_ascii=False),
        "fetched_at": rec["fetched_at"], "raw_file": raw_file,
    }
    upsert_citation(dbrow, db_path=db_path)
    return {"source": source, "paper_key": p["paper_key"], "status": rec["status"]}


def run_fetch(input_path=DEFAULT_INPUT, sources=None, refresh=False, threads=6,
              limit=None, db_path=DB_PATH):
    sources = sources or list(FETCHERS)
    for s in sources:
        if s not in FETCHERS:
            raise SystemExit(f"未知 source: {s}（可选 {list(FETCHERS)}）")
    papers = load_input(input_path)
    if limit:
        papers = papers[:limit]
    seen = set()
    papers = [p for p in papers if not (p["paper_key"] in seen or seen.add(p["paper_key"]))]

    conn = init_db(db_path)
    conn.close()
    upsert_papers(papers, db_path=db_path)
    conn = init_db(db_path)
    done = _done_sources(conn, refresh)
    conn.close()

    tasks = []
    for p in papers:
        for s in sources:
            if (p["paper_key"], s) in done:
                continue
            tasks.append((p, s))
    print(f"论文 {len(papers)} 篇，待拉取任务 {len(tasks)} 个（去重后）", flush=True)

    counts = {"ok": 0, "not_found": 0, "error": 0, "no_identifier": 0, "ok_titlesearch": 0}
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futs = {ex.submit(_task, p, s, refresh, db_path): (p, s) for p, s in tasks}
        done_n = 0
        for fut in as_completed(futs):
            p, s = futs[fut]
            try:
                r = fut.result()
                counts[r["status"]] = counts.get(r["status"], 0) + 1
            except Exception as e:  # noqa: BLE001
                counts["error"] += 1
                print(f"  [ERROR] {s} {p['paper_key']}: {e}", flush=True)
            done_n += 1
            if done_n % 40 == 0:
                print(f"  进度 {done_n}/{len(tasks)} ok={counts['ok']} err={counts['error']}",
                      flush=True)
    return counts


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    print(json.dumps(run_fetch(), ensure_ascii=False, indent=2))
