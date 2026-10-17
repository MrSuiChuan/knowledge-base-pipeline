#!/usr/bin/env python3
# Copyright 2026 AI实战技能圈
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""SessionEnd：宽限期退出时补捕获并提交会话（Codex >= 0.145 才会触发）。

本机 Codex 0.135 不触发这个事件；声明它不影响旧版本——旧版本/崩溃退出由
SessionStart 的空闲清扫兜底。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import emit, load_payload, project_root, trace_payload  # noqa: E402


def main() -> None:
    payload = load_payload()
    trace_payload("SessionEnd", payload)
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
        client = ov_memory.client_for_hook(root, timeout=8)
        ov_id = ov_memory.derive_ov_session_id(session_id or "manual")
        if transcript:
            ov_memory.capture_from_transcript(
                root, transcript, session_id, client=client, commit_threshold=0
            )
        client.commit(ov_id, keep_recent_count=0)
    except Exception:
        pass  # 退出路径上不打扰用户
    emit({})


if __name__ == "__main__":
    main()
