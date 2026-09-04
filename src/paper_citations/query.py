"""查询 API：DOI/刊名关键词检索论文被引（读本地库）。"""

from __future__ import annotations

from pathlib import Path

from .ids import norm_arxiv, norm_doi, norm_pmid, paper_key
from .report import get_paper_rows, merge_row
from .store import DB_PATH, connect
from . import fetch

# 已“尘埃落定”、无需再请求 API 的状态
_SETTLED = ("ok", "ok_titlesearch", "not_found", "no_identifier")


def _row_dict(r):
    d = {k: v for k, v in r.items() if k != "_by_source"}
    return d


def by_doi(db=DB_PATH, doi=None, include_all=False):
    """按 DOI 查一篇论文的合并结果。doi 可带 '10.x/..' 前缀。"""
    key = norm_doi(doi)
    for r in merged_rows_local(db):
        if r["doi"] == key:
            return (r if include_all else _row_dict(r)) or r
    return None


def merged_rows_local(db=DB_PATH):
    """读本地库合并结果（不触发任何网络请求）。"""
    from .report import merged_rows
    return merged_rows(db)


def search(db=DB_PATH, keyword=None, limit=50):
    """关键词匹配标题/期刊/标签。返回合并行列表。"""
    kw = (keyword or "").strip().lower()
    out = []
    for r in merged_rows_local(db):
        blob = " ".join(str(r.get(k) or "") for k in
                        ("title", "journal", "label", "doi")).lower()
        if not kw or kw in blob:
            out.append(_row_dict(r))
            if len(out) >= limit:
                break
    return out


def stats(db=DB_PATH):
    conn = connect(db, mode="ro")
    n = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    ncit = conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0]
    conn.close()
    return {"papers": n, "citation_rows": ncit}


def lookup(db=DB_PATH, doi=None, pmid=None, arxiv=None, title=None,
           sources=None, refresh=False):
    """缓存优先的单篇被引查询。

    流程：归一化 ID → 生成 paper_key → 若本地库已含全部 requested 源且状态稳定
    （ok/not_found/no_identifier），直接返回本地结果（不消耗 API 额度）；
    否则仅对缺失/出错/`refresh` 的源发一次请求并写回本地库，再返回合并结果。

    返回 {"merged": {...宽表字段, 无 _by_source},
          "by_source": {source: {...}},
          "cache": "hit" | "fresh",
          "fetched_sources": [...]}
    """
    from .report import decode_citation
    from .store import init_db, upsert_papers

    db = Path(db)
    doi = norm_doi(doi) if doi else None
    pmid = norm_pmid(pmid) if pmid else None
    arxiv = norm_arxiv(arxiv) if arxiv else None
    sources = sources or list(fetch.FETCHERS)
    key = paper_key(doi=doi, pmid=pmid, arxiv=arxiv, title=title)

    init_db(db)  # 确保表存在（可安全创建空库）
    conn = connect(db, mode="rw")
    p = conn.execute("SELECT * FROM papers WHERE paper_key=?", (key,)).fetchone()
    conn.close()

    prow = dict(p) if p else {"paper_key": key, "label": key, "doi": doi,
                              "pmid": pmid, "arxiv": arxiv, "title": title,
                              "journal": None, "year": None,
                              "source_input": "lookup"}
    # 补全/合并标识（同一 key 后续查询可能带更多 ID）
    for fld in ("doi", "pmid", "arxiv", "title", "journal", "year", "label"):
        val = {"doi": doi, "pmid": pmid, "arxiv": arxiv, "title": title}.get(fld)
        if val:
            prow[fld] = val
    upsert_papers([prow], db_path=db)

    _, cits = get_paper_rows(db, key)
    missing = []
    for s in sources:
        if refresh:
            missing.append(s)
        elif s not in cits or cits[s]["status"] not in _SETTLED:
            missing.append(s)

    if missing:
        for s in missing:
            # 复用 fetch 任务：拉取、存库、写结果缓存（含错误行留痕，便于下次命中本地）
            fetch._task(prow, s, refresh=False, db_path=db)
        _, cits = get_paper_rows(db, key)

    merged = merge_row(prow, cits)
    return {"merged": _row_dict(merged),
            "by_source": merged["_by_source"],
            "cache": "hit" if not missing else "fresh",
            "fetched_sources": missing}
