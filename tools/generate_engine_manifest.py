#!/usr/bin/env python3
# Copyright 2026 AI实战技能圈
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Regenerate engine/.engine-manifest.json after any engine/ code change.

Run from the repository root:

    python tools/generate_engine_manifest.py

The manifest is shipped inside engine/ so /kb-setup copies carry a sha256 baseline
used by ``kbp.py`` engine-integrity self-checks on the project-local ``.kb/engine``.

哈希走 ``context.sha256_file``（行尾先归一为 LF）：不能按原始字节比较，否则
本机 CRLF / 新克隆 LF 会让每个贡献者的自检全线失败——同一个作者的上一个插件
在这里踩过坑。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

from core import context  # noqa: E402  （复用完整性自检用的同一个哈希函数）


def build_manifest() -> dict:
    """按 engine/ 当前内容算出清单（纯函数：不写盘，便于测试比对）。"""
    manifest: dict[str, str] = {}
    for path in sorted(ENGINE.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        if path.name == ".engine-manifest.json":
            continue
        manifest[path.relative_to(ENGINE).as_posix()] = context.sha256_file(path)
    return manifest


def main() -> int:
    manifest = build_manifest()
    (ENGINE / ".engine-manifest.json").write_text(
        json.dumps({"schema_version": 1, "files": manifest}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"manifest written: {len(manifest)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
