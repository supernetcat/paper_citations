"""paper-citations · 论文被引量多源本地数据集。

从 OpenAlex(主) + Semantic Scholar/Crossref/Europe PMC(辅) 拉取论文被引数，
本地化存 SQLite + 原始响应缓存 + CSV/JSON 导出 + 查询模块。
纯标准库实现，无第三方依赖。
"""

from . import query, sources
from .store import DB_PATH

__version__ = "0.1.0"
