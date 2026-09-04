# paper-citations · 论文被引量多源本地数据集

把论文清单的**被引量**从多源拉取并**本地化**：`OpenAlex(主) + Semantic Scholar / Crossref / Europe PMC(辅)` → SQLite + 原始响应缓存 + CSV/JSON + 查询模块。
纯标准库，无第三方依赖。同构于 `journal-metrics`（期刊级指标）工程。

## 产物（outputs/）

| 文件 | 说明 |
|---|---|
| `citations.db` | SQLite 主库：`papers` / `citations`（每论文×每源） |
| `csv/papers_citations.csv` | 宽表：每篇论文一行，多源被引并列 + 最终口径 |
| `csv/citations_long.csv` | 长表：每论文×每源一条记录（含状态/原始值） |
| `json/citations.json` | 嵌套 JSON（按 paper_key） |
| `cache/raw/{source}/*.json` | **逐源抓取结果缓存**（含时间戳，可离线复查/审计） |
| `coverage_report.md/json` | 覆盖率、各源命中、无被引清单 |

## 数据规模（2026-09-04 实拉）

- 论文清单：**374** 篇（scholarminer 312 + scholar-scout 62 去重）+ 按需查询补充（如 NumPy 论文）
- 每个来源 × 每篇均尝试拉取；成功给出被引：
  | 源 | 命中 | 口径 |
  |---|---|---|
  | OpenAlex | 264 | 主源（宽覆盖） |
  | Semantic Scholar | 261 | 辅助 |
  | Crossref | 253 | 辅助（最低估） |
  | Europe PMC | 221 | 辅助（生物医学） |
- 至少一个源给出被引：**265 / 374 = 70.9%**（≥2 源交叉 262）
- 未命中主体为**中文期刊 DOI**（中华医学会等本地注册代理，非 Crossref 收录），无国际被引属正常，见 `coverage_report.md` 清单。

**多源数值天然不同**（同篇 NumPy：OpenAlex 23,533 / S2 22,136 / Crossref 24,062 / EPMC 7,572），报告请保留多列并注明来源与抓取时间。

## 查询自带本地缓存（省 API 额度）

`query <DOI>` 走**本地优先**：先按 DOI 查本地库，若四个源都已有“终态”结果
（成功 / 未收录 / 无标识）则**直接返回缓存，不发任何 API 请求**；只有缺失 / 上次失败
（error）/ `--refresh` 的源才会发请求，并把结果写回 SQLite 与 `cache/raw/`。

```bash
export OPENALEX_API_KEY=你的key
PYTHONPATH=src python3 -m paper_citations query "10.1038/s41586-020-2649-2"   # 首次：fresh，请求并缓存
PYTHONPATH=src python3 -m paper_citations query "10.1038/s41586-020-2649-2"   # 再次：本地缓存命中，0 API
PYTHONPATH=src python3 -m paper_citations query "10.1111/tri.13828" --refresh  # 强制重拉
```

程序内等价接口：`paper_citations.query.lookup(doi=..., refresh=False)`，
返回 `{"merged": {...}, "by_source": {...}, "cache": "hit"|"fresh", "fetched_sources": [...]}`。

> 说明：某源上次请求失败会记录为 `error`，下次查询会自动重试该源（其余仍走缓存）。
> OpenAlex 按 DOI 单篇免费、不消耗每日预算；批量列表更新用 `fetch`。

## 使用

```bash
# 环境：OpenAlex 免费 key（拉取必需，避免 429；勿入库/勿提交）
export OPENALEX_API_KEY=你的key

# 1) 从 scholarminer / scholar-scout 清单生成输入（也可手写 data/input/papers.csv）
PYTHONPATH=src python3 -m paper_citations build-input

# 2) 拉取（断点续跑：已成功的不重拉；--refresh 强制重拉；--limit N 试跑）
PYTHONPATH=src python3 -m paper_citations fetch [--sources openalex semanticscholar crossref europepmc] [--threads 6]

# 3) 导出 + 覆盖率报告
PYTHONPATH=src python3 -m paper_citations export
PYTHONPATH=src python3 -m paper_citations report

# 4) 查询
PYTHONPATH=src python3 -m paper_citations query "10.1111/tri.13828"
PYTHONPATH=src python3 -m paper_citations query "transplant"
```

程序内调用：

```python
import sys; sys.path.insert(0, "/usr/OpenCode/paper-citations/src")
from paper_citations.query import by_doi, search
m = by_doi("10.1111/tri.13828")
m["title"], m["cited_final"], m["cited_openalex"], m["cited_s2"], m["openalex_year_trend"]
```

## 输入清单格式（data/input/papers.csv）

```
label,doi,pmid,arxiv,title,journal,year,source_input
```

`doi/pmid/arxiv` 至少一个（否则该源记为 `no_identifier`，仅 OpenAlex 会对标题做一次检索）。

## 口径与注意

- **最终口径** `cited_final`：按 `openalex → semanticscholar → crossref → europepmc` 取第一个有值者（可改 `report.FINAL_ORDER`）。
- `cited_*` 各列**分别来自各源当日值**；`fetched_at` 记录抓取时间，被引数随时间增长，重跑即更新。
- OpenAlex 无 key 只有 $0.1/天匿名额度 → 易 429；带免费 key 为 $1/天，且“按 DOI 单篇”**免费**。key 从环境变量 `OPENALEX_API_KEY` 读取，代码不内置。
- DOI 清洗内置处理：Unicode 连字符（如 `‑` U+2011）→ `-`；剥离粘附的收录来源后缀（`…440-5PMC`/`PubMed`/`Semantic Scholar`）；剥离中文尾缀。中文期刊若用本地代理 DOI，各国际源查不到属正常。
- 合规：数据仅供内部检索；对外报告建议用 Scopus/WoS 官方口径并注明抓取日。

## 打包与二进制发布

提供 **GitHub Actions**（`.github/workflows/build-binaries.yml`）：在 `v*` 标签或手动触发时，用 PyInstaller 在
Linux/macOS/Windows 三平台各产出一个免安装二进制，作为 Release 附件或 Artifact。

本地（Linux/macOS/Windows 各自本机）也可直接打包：

```bash
python -m pip install pyinstaller
python -m PyInstaller --onefile --name paper-citations \
  --paths src --clean --noconfirm scripts/paper_citations_entry.py
# 产物：dist/paper-citations (Windows 为 .exe)
```

二进制运行时的数据目录固定在**可执行文件所在目录**（`<dir>/outputs`、`<dir>/data/input/papers.csv`），
不影响源码运行方式。

> 仓库不提交运行时数据：`data/input/*.csv`（除 `sample_input.csv` 样例）、`outputs/`、`data/custom/` 均在 `.gitignore` 内。
> 样例清单见 `data/input/sample_input.csv`（可直接 `fetch --input data/input/sample_input.csv`）。

## 目录

```
paper-citations/
├── .github/workflows/build-binaries.yml   # 三平台 PyInstaller 打包
├── data/input/sample_input.csv            # 公开样例清单（私有 papers.csv 不入库）
├── scripts/paper_citations_entry.py       # PyInstaller 入口
├── src/paper_citations/
│   ├── ids.py / http.py / paths.py        # ID 归一化 / HTTP 重试 / 运行时路径
│   ├── sources.py                         # 四源拉取器
│   ├── fetch.py                           # 编排（并发/断点续跑/结果缓存）
│   ├── store.py / report.py               # SQLite / 合并+导出+覆盖率
│   ├── query.py                           # 查询 API（本地缓存优先）
│   └── __main__.py                        # CLI
└── outputs/…                              # 本地运行时产物（不入库）
```
