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
"""PostToolUse hook：软提醒——改了知识内容就提醒重跑审计（不阻断）。"""

from __future__ import annotations

from pathlib import Path

from common import emit, load_payload, project_root  # noqa: E402


def main() -> None:
    payload = load_payload()
    root = project_root(payload)
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    if tool_name in ("Write", "Edit", "MultiEdit"):
        file_path = str(tool_input.get("file_path") or tool_input.get("path") or "")
        if root and file_path:
            path = Path(file_path)
            rel_lower = str(path).lower().replace("\\", "/")
            if root and (".kb/repo/domains/" in rel_lower or ".kb/repo/rules/" in rel_lower):
                emit(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUse",
                            "additionalContext": (
                                "[knowledge-base-plugin] 知识内容已变更：发布前必须重跑 "
                                "kbp audit --mode publish --level strict；规则文件只应经提案写入。"
                            ),
                        }
                    }
                )
                return
    emit({})


if __name__ == "__main__":
    main()
