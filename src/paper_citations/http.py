"""轻量 HTTP：UA、超时、重试与退避。纯 urllib 实现。"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request

MAILTO = os.environ.get("JM_MAILTO", "journal-metrics@local")

_UA = {"User-Agent": "paper-citations/0.1 (mailto:%s)" % MAILTO}


def _opener():
    return urllib.request.build_opener()


def get_json(url: str, timeout: float = 30.0, retries: int = 6, headers: dict | None = None,
             params: dict | None = None) -> dict | list | None:
    """GET JSON。HTTP 404/400/422 返回 None；429/403 退避重试；其余异常抛 HTTPError/URLError。"""
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    h = dict(_UA)
    if headers:
        h.update(headers)
    last = None
    for attempt in range(retries):
        time.sleep(0.15 * attempt)  # 平缓起步，避免突发打满限频
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (404, 400, 422):
                return None
            if e.code in (403, 429):
                last = e
                wait = 1.0
                try:
                    wait = float(e.headers.get("Retry-After", "1"))
                except (TypeError, ValueError):
                    wait = 1.0
                time.sleep(wait * (2 ** attempt))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(1.5 ** attempt + random.random())
                continue
    if isinstance(last, Exception):
        raise last
    return None
