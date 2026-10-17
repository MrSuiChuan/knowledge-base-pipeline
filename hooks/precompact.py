#!/usr/bin/env python3
# Copyright 2026 AI实战技能圈
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""PreCompact：上下文压缩前补捕获剩余轮次并提交会话。

对齐 OpenViking 官方 Codex 插件（scripts/pre-compact-capture.mjs）。压缩会重写
transcript，所以必须在这里把"已经发生但还没落库"的轮次补齐，并触发提交让抽取跑起来。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import emit, load_payload, project_root, trace_payload  # noqa: E402


def main() -> None:
    payload = load_payload()
    trace_payload("PreCompact", payload)
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
        session_id = str(payload.get("session_id") or "").strip() or None
        client = ov_memory.client_for_hook(root, timeout=20)
        ov_id = ov_memory.derive_ov_session_id(session_id or "manual")
        if transcript:
            ov_memory.capture_from_transcript(
                root, transcript, session_id, client=client, commit_threshold=0
            )
        client.commit(ov_id, keep_recent_count=0)
        emit({})
    except Exception as exc:  # fail-open：压缩本身不能被记忆链路拖垮
        emit({"systemMessage": f"[knowledge-base-plugin] 压缩前提交失败（fail-open）: {type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
