"""CLI：build-input / fetch / export / report / query。"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from .ids import extract_doi
from . import fetch, report
from . import query as qapi
from .store import DB_PATH

ROOT = Path(__file__).resolve().parents[2]


def build_input(scholarminer, scholar_scout, out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    seen = {}
    if scholarminer and Path(scholarminer).exists():
        data = json.load(open(scholarminer, encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("papers", [])
        for it in items:
            doi = extract_doi(it.get("doi_raw") or it.get("doi"))
            title = it.get("title")
            if not doi and not title:
                continue
            year = re.match(r"(\d{4})", str(it.get("date_raw") or "")).group(1) \
                if re.match(r"(\d{4})", str(it.get("date_raw") or "")) else None
            seen.setdefault(doi or ("T:" + str(title)[:40]), {
                "label": f"scholarminer-{it.get('row','')}", "doi": doi or "",
                "pmid": "", "arxiv": "", "title": title or "", "journal": it.get("journal") or "",
                "year": year or "", "source_input": "scholarminer"})
    if scholar_scout and Path(scholar_scout).exists():
        data = json.load(open(scholar_scout, encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("papers", [])
        for it in items:
            doi = extract_doi(it.get("doi") or it.get("doi_raw"))
            title = it.get("title")
            if not doi and not title:
                continue
            key = doi or ("T:" + str(title)[:40])
            if key in seen:
                rec = seen[key]
                if doi and not rec["doi"]:
                    rec["doi"] = doi
                rec["pmid"] = rec["pmid"] or str(it.get("pmid") or "")
                rec["year"] = rec["year"] or str(it.get("year") or "")
            else:
                seen[key] = {"label": f"scholar-scout-{it.get('row','')}",
                             "doi": doi or "", "pmid": str(it.get("pmid") or ""),
                             "arxiv": "", "title": title or "",
                             "journal": it.get("journal") or "",
                             "year": str(it.get("year") or ""),
                             "source_input": "scholar-scout"}
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["label", "doi", "pmid", "arxiv",
                                          "title", "journal", "year", "source_input"])
        w.writeheader()
        for r in seen.values():
            w.writerow(r)
    print(f"写入 {len(seen)} 篇 -> {out}")


def cmd_fetch(a):
    counts = fetch.run_fetch(input_path=a.input, sources=a.sources,
                             refresh=a.refresh, threads=a.threads,
                             limit=a.limit, db_path=a.db)
    print(json.dumps(counts, ensure_ascii=False, indent=2))


def cmd_export(a):
    report.export(a.db)
    print("导出 ->", report.CSV_DIR, "&", report.JSON_DIR)


def cmd_report(a):
    r = report.coverage(a.db)
    print(json.dumps(r, ensure_ascii=False, indent=2))


def cmd_query(a):
    kw = a.keyword
    if a.lookup or _looks_like_doi(kw):
        out = qapi.lookup(db=a.db, doi=kw, refresh=a.refresh)
        tag = "本地缓存命中（未请求 API）" if out["cache"] == "hit" else \
            f"fresh：已请求 {out['fetched_sources']} 并写缓存"
        print(f"# {tag}")
        _print_row(out["merged"])
        return
    hits = qapi.search(db=a.db, keyword=kw, limit=a.limit)
    if not hits:
        print("无匹配")
        return
    for h in hits:
        _print_row(h)


def _looks_like_doi(s: str) -> bool:
    return "10." in (s or "").lower()[:12] or (s or "").lower().startswith("doi:")


def _print_row(m):
    print(f"[{m.get('paper_key')}] {m.get('label') or ''}")
    print(f"  {m.get('title')}")
    print(f"  journal={m.get('journal')} year={m.get('year')} doi={m.get('doi')} "
          f"pmid={m.get('pmid')}")
    print(f"  cited_final={m.get('cited_final')} ({m.get('final_source')})   "
          f"OpenAlex={m.get('cited_openalex')} S2={m.get('cited_s2')} "
          f"(infl {m.get('influential_s2')}) Crossref={m.get('cited_crossref')} "
          f"EPMC={m.get('cited_europepmc')}")


def cmd_build_input(a):
    build_input(a.scholarminer, a.scholar_scout, a.out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="paper-citations",
                                 description="论文被引量多源本地数据集")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build-input", help="从 scholarminer/scholar-scout 清单生成输入 CSV")
    b.add_argument("--scholarminer", default=str(ROOT.parent / "scholarminer/data/papers_final.json"))
    b.add_argument("--scholar-scout", default=str(ROOT.parent / "scholar-scout/data/papers_unified.json"))
    b.add_argument("--out", default=str(fetch.DEFAULT_INPUT))
    b.set_defaults(func=cmd_build_input)

    f = sub.add_parser("fetch", help="拉取各源被引")
    f.add_argument("--input", default=str(fetch.DEFAULT_INPUT))
    f.add_argument("--sources", nargs="*",
                   default=["openalex", "semanticscholar", "crossref", "europepmc"])
    f.add_argument("--refresh", action="store_true", help="忽略已缓存结果重新拉取")
    f.add_argument("--threads", type=int, default=6)
    f.add_argument("--limit", type=int, default=None)
    f.add_argument("--db", default=str(DB_PATH))
    f.set_defaults(func=cmd_fetch)

    e = sub.add_parser("export", help="导出 CSV/JSON")
    e.add_argument("--db", default=str(DB_PATH))
    e.set_defaults(func=cmd_export)

    r = sub.add_parser("report", help="覆盖率报告")
    r.add_argument("--db", default=str(DB_PATH))
    r.set_defaults(func=cmd_report)

    q = sub.add_parser("query", help="查询（DOI 或关键词；DOI 走本地缓存优先）")
    q.add_argument("keyword")
    q.add_argument("--lookup", action="store_true",
                   help="强制按 DOI/关键词做缓存优先查询（即便不是标准 DOI 形态）")
    q.add_argument("--refresh", action="store_true", help="忽略本地缓存，强制重新拉取")
    q.add_argument("--limit", type=int, default=10)
    q.add_argument("--db", default=str(DB_PATH))
    q.set_defaults(func=cmd_query)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
