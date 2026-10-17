#!/usr/bin/env python3
# Copyright 2026 AI实战技能圈
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""UserPromptSubmit：按当前 prompt 召回 OpenViking 记忆，注入 additionalContext。

对齐 OpenViking 官方 Codex 插件（examples/codex-memory-plugin/scripts/auto-recall.mjs）：
检索失败、服务不可达、记忆未启用一律 fail-open（静默返回 {}），绝不打断这一轮对话。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import emit, load_payload, project_root, trace_payload  # noqa: E402


def main() -> None:
    payload = load_payload()
    trace_payload("UserPromptSubmit", payload)
    root = project_root(payload)
    if root is None:
        emit({})
    try:
        from core import context, ov_memory  # 惰性导入：与既有 hook 一致

        config = context.load_config(root)
        ov = config.get("ov") or {}
        if not ov_memory.is_enabled(config) or ov.get("auto_recall") is False:
            emit({})
        prompt = str(payload.get("prompt") or "").strip()
        if len(prompt) < 3:
            emit({})
        try:
            budget = float(ov.get("recall_timeout_s") or 8)
        except (TypeError, ValueError):
            budget = 8.0
        block = ov_memory.recall_block(
            root,
            prompt,
            limit=int(ov.get("recall_limit") or 6),
            client=ov_memory.client_for_hook(root, timeout=budget),
            max_chars=3500,
        )
        if not block:
            emit({})
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": block,
                }
            }
        )
    except Exception:  # fail-open：召回失败不能打断对话
        emit({})


if __name__ == "__main__":
    main()
