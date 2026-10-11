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
"""Package this plugin folder into a Claude Code marketplace repo.

Usage:
    python tools/wrap_marketplace.py <target-repo-root> [--name personal]

Then:
    claude plugin marketplace add <target-repo-root>
    claude plugin install knowledge-base-plugin
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# Windows 上 stdout 被重定向时是 cp1252/cp936，中文进度行会直接 UnicodeEncodeError。
# 交互式控制台走 PEP 528 的宽字符 API，本来就支持中文，这里的 reconfigure 是空操作。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PLUGIN_NAME = "knowledge-base-plugin"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("--name", default="personal")
    args = parser.parse_args()
    target = Path(args.target).resolve()
    dst = target / "plugins" / PLUGIN_NAME
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        PLUGIN_ROOT,
        dst,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".kb"),
    )
    manifest_dir = target / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    marketplace = {
        "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
        "name": args.name,
        "description": "数仓知识库生成流水线插件（knowledge-base-plugin 的本地 marketplace 包装）",
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "description": "采集→结构化→质检→审阅→发布→反哺→沉淀 的知识库工艺流水线",
                "author": {"name": "knowledge-base-plugin maintainers"},
                "source": f"./plugins/{PLUGIN_NAME}",
                "category": "development",
            }
        ],
    }
    (manifest_dir / "marketplace.json").write_text(
        json.dumps(marketplace, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "marketplace_root": str(target)}, ensure_ascii=False, indent=2))
    print(f"\n安装：\n  claude plugin marketplace add {target}\n  claude plugin install {PLUGIN_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
