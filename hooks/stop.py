#!/usr/bin/env python3
# Copyright 2026 AI实战技能圈
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Stop：每轮结束把新增的 user/assistant 轮次追加进 OpenViking 会话。

对齐 OpenViking 官方 Codex 插件（scripts/auto-capture.mjs）：payload 里的
``session_id`` 决定会话（`cx-<id>`），``transcript_path`` 是 Codex rollout。
去重靠本插件自己的水位（.kb/runtime/memory/host-sessions.json）。
失败只提示、不阻断（Stop 的决策输出是 {}）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import emit, load_payload, project_root, trace_payload  # noqa: E402


def main() -> None:
    payload = load_payload()
    trace_payload("Stop", payload)
    root = project_root(payload)
    if root is None:
        emit({})
    try:
        from core import context, ov_memory

        config = context.load_config(root)
        ov = config.get("ov") or {}
        if not ov_memory.is_enabled(config) or ov.get("auto_capture") is False:
            emit({})
        transcript = str(payload.get("transcript_path") or "").strip()
        if not transcript:
            emit({})
        ov_memory.capture_from_transcript(
            root,
            transcript,
            str(payload.get("session_id") or "").strip() or None,
            client=ov_memory.client_for_hook(root, timeout=12),
        )
        emit({})
    except Exception as exc:  # fail-open：捕获失败只提示
        emit({"systemMessage": f"[knowledge-base-plugin] 自动捕获失败（fail-open）: {type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
