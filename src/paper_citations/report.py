"""合并口径 + 导出(CSV/JSON) + 覆盖率报告。"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from .store import OUT, connect

# 报告最终口径的来源优先级（前有则取前，专给“主被引数”一个确定值）
FINAL_ORDER = ["openalex", "semanticscholar", "crossref", "europepmc"]
SRC_LABEL = {"openalex": "OpenAlex", "semanticscholar": "Semantic Scholar",
             "crossref": "Crossref", "europepmc": "Europe PMC"}
CSV_DIR = OUT / "csv"
JSON_DIR = OUT / "json"


def _fetch_all(db_path):
    conn = connect(db_path, mode="ro")
    papers = [dict(r) for r in conn.execute("SELECT * FROM papers ORDER BY paper_key")]
    cits = {}
    for r in conn.execute("SELECT * FROM citations ORDER BY paper_key, source"):
        d = dict(r)
        d["counts_by_year"] = json.loads(d.pop("counts_by_year_json") or "[]")
        d["extra"] = json.loads(d.pop("extra_json") or "{}")
        cits.setdefault(d["paper_key"], {})[d["source"]] = d
    conn.close()
    return papers, cits


def merge_row(p: dict, c: dict) -> dict:
    """单篇合并：papers 行 p + {source: citations 行} → 宽表字典。"""
    got = {s: c[s]["cited_by"] for s in c
           if c[s]["status"] in ("ok", "ok_titlesearch") and c[s]["cited_by"] is not None}
    final_src = next((s for s in FINAL_ORDER if s in got), None)
    ok_sources = [s for s in FINAL_ORDER if s in c and c[s]["status"] in ("ok", "ok_titlesearch")]
    title = None
    journal = None
    year = None
    for s in FINAL_ORDER:
        if s in c and c[s]["title"]:
            title = c[s]["title"]; break
    for s in FINAL_ORDER:
        if s in c and c[s]["journal"]:
            journal = c[s]["journal"]; break
    for s in FINAL_ORDER:
        if s in c and c[s]["year"]:
            year = c[s]["year"]; break
    title = title or p["title"]
    journal = journal or p["journal"]
    year = year or p["year"]
    oa = c.get("openalex")
    s2 = c.get("semanticscholar")
    cr = c.get("crossref")
    ep = c.get("europepmc")
    return {
        "paper_key": p["paper_key"], "label": p["label"],
        "doi": p["doi"], "pmid": p["pmid"], "arxiv": p["arxiv"],
        "title": title, "journal": journal, "year": year,
        "cited_final": got.get(final_src) if final_src else None,
        "final_source": SRC_LABEL.get(final_src) if final_src else None,
        "cited_openalex": got.get("openalex"),
        "cited_s2": got.get("semanticscholar"),
        "influential_s2": s2["influential"] if s2 and s2["status"] == "ok" else None,
        "cited_crossref": got.get("crossref"),
        "cited_europepmc": got.get("europepmc"),
        "sources_ok": len(ok_sources),
        "openalex_year_trend": (oa["counts_by_year"] if oa and oa["status"] == "ok" else None),
        "openalex_work_id": (oa["work_id"] if oa else None),
        "s2_paper_id": (s2["work_id"] if s2 else None),
        "pmcid": (ep["extra"].get("pmcid") if ep else None),
        "fetched_at": (max((c[s]["fetched_at"] for s in c), default=None)),
        "_by_source": {s: c[s] for s in c},
    }


def merged_rows(db_path):
    papers, cits = _fetch_all(db_path)
    return [merge_row(p, cits.get(p["paper_key"], {})) for p in papers]


def decode_citation(row) -> dict:
    d = dict(row)
    d["counts_by_year"] = json.loads(d.pop("counts_by_year_json") or "[]")
    d["extra"] = json.loads(d.pop("extra_json") or "{}")
    return d


def get_paper_rows(db_path, key):
    """取单篇：返回 (paper dict, {source: decoded citation row})。没有则为 (None, {})。"""
    conn = connect(db_path, mode="ro")
    p = conn.execute("SELECT * FROM papers WHERE paper_key=?", (key,)).fetchone()
    cits = {}
    if p:
        for r in conn.execute("SELECT * FROM citations WHERE paper_key=?", (key,)):
            cits[r["source"]] = decode_citation(r)
    conn.close()
    return (dict(p) if p else None), cits


def export(db_path):
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    rows = merged_rows(db_path)
    cols = ["paper_key", "label", "doi", "pmid", "arxiv", "title", "journal", "year",
            "cited_final", "final_source", "cited_openalex", "cited_s2",
            "influential_s2", "cited_crossref", "cited_europepmc", "sources_ok",
            "openalex_work_id", "s2_paper_id", "pmcid", "fetched_at"]

    def v(x):
        if x is None:
            return ""
        if isinstance(x, list):
            return json.dumps(x, ensure_ascii=False)
        return x

    with open(CSV_DIR / "papers_citations.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: v(r.get(k)) for k in cols})

    with open(CSV_DIR / "citations_long.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["paper_key", "label", "source", "status", "cited_by", "year",
                    "title", "journal", "work_id", "fetched_at", "extra"])
        for r in rows:
            for s, d in r["_by_source"].items():
                w.writerow([r["paper_key"], r["label"], s, d["status"], d["cited_by"],
                            d["year"], d["title"], d["journal"], d["work_id"],
                            d["fetched_at"], json.dumps(d["extra"], ensure_ascii=False)])

    nested = {}
    for r in rows:
        d = {k: r.get(k) for k in cols}
        d.pop("_by_source", None)
        d["year_trend"] = r["openalex_year_trend"]
        nested[r["paper_key"]] = d
    with open(JSON_DIR / "citations.json", "w", encoding="utf-8") as f:
        json.dump(nested, f, ensure_ascii=False, separators=(",", ":"))


def coverage(db_path):
    rows = merged_rows(db_path)
    total = len(rows)
    per_src = Counter()
    with_count = Counter()
    for r in rows:
        for s, d in r["_by_source"].items():
            per_src[s] += 1
            if d["status"] in ("ok", "ok_titlesearch") and d["cited_by"] is not None:
                with_count[s] += 1
    final_ok = sum(1 for r in rows if r["cited_final"] is not None)
    multi = sum(1 for r in rows if r["sources_ok"] >= 2)
    diffs = []
    oa_s2 = [(r["cited_openalex"], r["cited_s2"]) for r in rows
             if r["cited_openalex"] is not None and r["cited_s2"] is not None]
    rep = {
        "total_papers": total,
        "final_coverage": final_ok,
        "final_coverage_pct": round(final_ok / total * 100, 1) if total else None,
        ">=2_sources": multi,
        "per_source_ok": {s: with_count[s] for s in per_src},
        "per_source_attempted": dict(per_src),
        "openalex_vs_s2_pairs": len(oa_s2),
        "no_any_count_papers": [r["paper_key"] for r in rows if r["cited_final"] is None],
    }
    with open(OUT / "coverage_report.json", "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    with open(OUT / "coverage_report.md", "w", encoding="utf-8") as f:
        f.write("# 论文被引量 · 覆盖率报告\n\n")
        f.write(f"论文总数：**{total}**；至少一个源给出被引：**{final_ok}**"
                f"（{rep['final_coverage_pct']}%）；≥2 源交叉：{multi}\n\n")
        f.write("| 来源 | 尝试 | 成功给出被引 |\n|---|---|---|\n")
        for s in per_src:
            f.write(f"| {SRC_LABEL.get(s, s)} | {per_src[s]} | {with_count[s]} |\n")
        f.write("\n无任何源被引（待补/无DOI）：\n\n")
        for k in rep["no_any_count_papers"][:200]:
            f.write(f"- `{k}`\n")
    return rep
