"""文献标识符归一化工具。"""

from __future__ import annotations

import hashlib
import re

_DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>，。；]+)", re.I)

# 常见被粘附在 DOI 末尾的“收录来源”后缀（源自某些清单导出拼接）
_GLUE_TOKENS = ["semantic scholar", "semanticscholar", "semantic", "pubmed", "pmc",
                "crossref", "openalex", "wos", "cnki", "scopus", "europepmc",
                "doaj", "scilit", "x-mol", "scienceopen", "scinapse", "paperdigest"]


def _glue_dash(s: str) -> str:
    """把各种 Unicode 连字符/短横统一成 ASCII '-'。"""
    out = []
    for ch in s:
        if ch in "‐‑‒–—―−﹣－":
            out.append("-")
        else:
            out.append(ch)
    return "".join(out)


def _strip_glue(s: str) -> str:
    """反复剥离粘附在 DOI 尾部的来源后缀（不区分大小写）。"""
    lowered = {t.lower(): t for t in _GLUE_TOKENS}
    changed = True
    while changed and s:
        changed = False
        low = s.lower()
        for tok in sorted(lowered, key=len, reverse=True):
            if low.endswith(tok) and len(s) > len(tok) + 5:
                s = s[:-len(tok)]
                changed = True
                low = s.lower()
        # 去掉纯尾随标点
        if s.endswith((".", ",", ";", "(", ")")):
            s = s[:-1]
            changed = True
    # 去掉粘附的 CJK（非 ASCII）尾部：DOI 不可能以中文字符结尾
    while s and ord(s[-1]) > 0x2E7F:
        s = s[:-1]
    return s


def norm_doi(raw: str | None) -> str | None:
    """DOI：去常见前缀、统一连字符、剥离粘附后缀、小写化。失败返回 None。"""
    if not raw:
        return None
    s = re.sub(r"^(doi|https?://(dx\.)?doi\.org/|https?://doi\.org/)", "",
               str(raw).strip(), flags=re.I)
    s = s.strip()
    s = _glue_dash(s)
    s = _strip_glue(s)
    s = s.rstrip(".")
    s = s.lower()
    if not s or not re.match(r"^10\.\d{4,9}/", s):
        return None
    return s


def extract_doi(text: str | None) -> str | None:
    """从自由文本中抽出 DOI（如 'DOI: 10.12659/AOT.929259'）。"""
    if not text:
        return None
    m = _DOI_RE.search(str(text))
    return norm_doi(m.group(1).rstrip(".,;")) if m else None


def norm_pmid(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    if s.lower().startswith("pmid:"):
        s = s[5:]
    if s.isdigit():
        return s
    return None


def norm_arxiv(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    s = re.sub(r"^(https?://arxiv\.org/(abs|pdf)/)", "", s, flags=re.I)
    s = s.split("?")[0]
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", s) or re.match(r"^[a-z-]+/\d{7}$", s):
        return s.lower()
    return None


def paper_key(doi=None, pmid=None, arxiv=None, title=None) -> str:
    """论文主键：优先 DOI；否则对标识/标题做稳定哈希，前缀 x。"""
    if doi:
        return norm_doi(doi) or ("x" + _h("|".join(filter(None, [doi, pmid, arxiv, title]))))
    raw = "|".join(str(v) for v in (pmid, arxiv, title) if v)
    if not raw:
        raise ValueError("paper_key 需要至少一个标识")
    return "x" + _h(raw)


def _h(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]
