"""运行时路径：区分 源码运行 与 PyInstaller 冻结二进制。

源码：以包所在项目根为基准；冻结：以可执行文件所在目录为基准（数据写其旁边）。
"""

from __future__ import annotations

import sys
from pathlib import Path


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller 打包后
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]
