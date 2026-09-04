"""多源被引数拉取器：OpenAlex(主) + Semantic Scholar/Crossref/Europe PMC(辅)。

统一输出 record 字段：
  source, status(ok/not_found/no_identifier/error/title_search),
  cited_by, counts_by_year(list|None), influential, reference_count,
  work_id, title, journal, issn, year, extra(dict)

实现需做到：404/无此记录 → not_found；缺标识 → no_identifier；网络异常 → error 并留 extra.error。
"""

from __future__ import annotations

import urllib.parse

from .ids import norm_doi
from .http import get_json

OPENALEX = "https://api.openalex.org"
S2 = "https://api.semanticscholar.org/graph/v1"
CROSSREF = "https://api.crossref.org"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"

S2_FIELDS = ("title,year,citationCount,influentialCitationCount,referenceCount,"
             "externalIds,venue,publicationTypes")

import os as _os


def _oa_auth():
    """OpenAlex 鉴权：优先 api_key（环境变量 OPENALEX_API_KEY），否则回退 mailto。"""
    key = _os.environ.get("OPENALEX_API_KEY")
    if key:
        return {"api_key": key.strip()}
    return {"mailto": _os.environ.get("JM_MAILTO", "journal-metrics@local")}


def _base(rec, source, status):
    return {"source": source, "status": status, "cited_by": None,
            "counts_by_year": None, "influential": None, "reference_count": None,
            "work_id": None, "title": None, "journal": None, "issn": None,
            "year": None, "extra": rec}


def _lastid(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1] if url else None


def _tl(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


# ---------------------------------------------------------------- OpenAlex

def fetch_openalex(doi=None, pmid=None, arxiv=None, title=None):
    params = dict(_oa_auth())
    try:
        if doi:
            d = get_json(f"{OPENALEX}/works/https://doi.org/{doi}", params=params)
            status = "ok" if d else "not_found"
            return _parse_openalex(d) if d else _base({}, "openalex", status)
        if pmid:
            d = get_json(f"{OPENALEX}/works", params={**params,
                          "filter": f"pmid:{pmid}", "per-page": "1"})
            res = (d or {}).get("results") or []
            if not res:
                return _base({}, "openalex", "not_found")
            return _parse_openalex(res[0])
        if arxiv:
            d = get_json(f"{OPENALEX}/works", params={**params,
                          "filter": f"locations.landing_page_url:arxiv.org/{arxiv}",
                          "per-page": "1"})
            res = (d or {}).get("results") or []
            if not res:
                return _base({}, "openalex", "not_found")
            return _parse_openalex(res[0])
        if title:
            d = get_json(f"{OPENALEX}/works", params={**params,
                          "filter": "title.search:" + title, "per-page": "1",
                          "select": "id,doi,title,publication_year,cited_by_count,"
                                    "counts_by_year,primary_location"})
            res = (d or {}).get("results") or []
            if not res:
                return _base({}, "openalex", "not_found")
            return _parse_openalex(res[0], title_search=True)
        return _base({}, "openalex", "no_identifier")
    except Exception as e:  # noqa: BLE001
        return {**_base({"error": str(e)}, "openalex", "error")}


def _parse_openalex(w, title_search=False):
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    rec = {
        "source": "openalex",
        "status": "ok_titlesearch" if title_search else "ok",
        "cited_by": w.get("cited_by_count"),
        "counts_by_year": [{"year": c.get("year"), "cited": c.get("cited_by_count")}
                           for c in (w.get("counts_by_year") or [])] or None,
        "influential": None,
        "reference_count": None,
        "work_id": _lastid(w.get("id")),
        "title": w.get("title") or w.get("display_name"),
        "journal": src.get("display_name"),
        "issn": (src.get("issn") or [None])[0],
        "year": w.get("publication_year"),
        "extra": {"doi": w.get("doi"), "pmid": w.get("pmid"),
                  "type": w.get("type"), "publisher": src.get("host_organization_name")},
    }
    return rec


# ---------------------------------------------------------------- Semantic Scholar

def fetch_s2(doi=None, pmid=None, arxiv=None, title=None):
    idkey = None
    if doi:
        idkey = f"DOI:{norm_doi(doi)}"
    elif pmid:
        idkey = f"PMID:{pmid}"
    elif arxiv:
        idkey = f"ARXIV:{arxiv}"
    if not idkey:
        return _base({}, "semanticscholar", "no_identifier")
    try:
        url = f"{S2}/paper/{idkey}"
        d = get_json(url, params={"fields": S2_FIELDS})
        if not d:
            return _base({}, "semanticscholar", "not_found")
        return {
            "source": "semanticscholar",
            "status": "ok",
            "cited_by": d.get("citationCount"),
            "counts_by_year": None,
            "influential": d.get("influentialCitationCount"),
            "reference_count": d.get("referenceCount"),
            "work_id": d.get("paperId"),
            "title": d.get("title"),
            "journal": (d.get("venue") or (d.get("publicationVenue") or {}).get("name")),
            "issn": None,
            "year": d.get("year"),
            "extra": {"externalIds": d.get("externalIds") or {}},
        }
    except Exception as e:  # noqa: BLE001
        return {**_base({"error": str(e)}, "semanticscholar", "error")}


# ---------------------------------------------------------------- Crossref

def fetch_crossref(doi=None, pmid=None, arxiv=None, title=None):
    if not doi:
        return _base({}, "crossref", "no_identifier")
    try:
        url = f"{CROSSREF}/works/{urllib.parse.quote(norm_doi(doi) or doi, safe='')}"
        d = get_json(url, headers={"User-Agent": "paper-citations/0.1 (mailto:journal-metrics@local)"})
        if not d:
            return _base({}, "crossref", "not_found")
        m = d.get("message") or {}
        issn = m.get("ISSN") or []
        return {
            "source": "crossref",
            "status": "ok",
            "cited_by": m.get("is-referenced-by-count"),
            "counts_by_year": None,
            "influential": None,
            "reference_count": None,
            "work_id": norm_doi(doi),
            "title": _tl(m.get("title")),
            "journal": _tl(m.get("container-title")),
            "issn": issn[0] if issn else None,
            "year": ((m.get("published") or {}).get("date-parts") or [[None]])[0][0],
            "extra": {"pending": m.get("is-referenced-by-counting-pending"),
                      "publisher": m.get("publisher"),
                      "type": m.get("type")},
        }
    except Exception as e:  # noqa: BLE001
        return {**_base({"error": str(e)}, "crossref", "error")}


# ---------------------------------------------------------------- Europe PMC

def fetch_europepmc(doi=None, pmid=None, arxiv=None, title=None):
    try:
        if doi:
            query = f'DOI:"{norm_doi(doi)}"'
        elif pmid:
            query = f'EXT_ID:{pmid} AND SRC:MED'
        else:
            return _base({}, "europepmc", "no_identifier")
        d = get_json(f"{EPMC}/search", params={
            "query": query, "format": "json", "resultType": "core", "pageSize": "1"})
        if not d:
            return _base({}, "europepmc", "not_found")
        res = ((d or {}).get("resultList") or {}).get("result") or []
        if not res:
            return _base({}, "europepmc", "not_found")
        r = res[0]
        return {
            "source": "europepmc",
            "status": "ok",
            "cited_by": r.get("citedByCount"),
            "counts_by_year": None,
            "influential": None,
            "reference_count": None,
            "work_id": r.get("pmcid") or r.get("id"),
            "title": r.get("title"),
            "journal": r.get("journalInfo", {}).get("journal", {}).get("title") or r.get("journalTitle"),
            "issn": (r.get("journalInfo", {}).get("journal", {}) or {}).get("issn"),
            "year": int(r["pubYear"]) if str(r.get("pubYear", "")).isdigit() else None,
            "extra": {"pmid": r.get("pmid"), "pmcid": r.get("pmcid"),
                      "authors": r.get("authorString"),
                      "isOpenAccess": r.get("isOpenAccess"),
                      "inEPMC": r.get("inEPMC")},
        }
    except Exception as e:  # noqa: BLE001
        return {**_base({"error": str(e)}, "europepmc", "error")}


FETCHERS = {
    "openalex": fetch_openalex,
    "semanticscholar": fetch_s2,
    "crossref": fetch_crossref,
    "europepmc": fetch_europepmc,
}
