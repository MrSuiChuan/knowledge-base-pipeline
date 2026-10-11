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
"""SessionStart hook：展示 .kb 状态与待审中间态。"""

from __future__ import annotations

from common import command_hint, emit, host_name, load_payload, plugin_version, project_root  # noqa: E402

from core import context, ov_memory, proposals  # noqa: E402


def _memory_note(root) -> str:
    """会话记忆启用时，开场就把会话绑定好（已有会话则原样复用）。

    这条路径必须 **fail-open**：记忆链路（网络、配额、服务端）出任何问题都不能打断会话启动，
    所以异常一律吞掉，只在成功时给一行提示。
    """
    try:
        settings = ov_memory.memory_settings(context.load_config(root))
        if not settings.get("enabled"):
            return ""
        tail = "；收工前跑 `memory commit`（归档并触发记忆抽取，会消耗模型配额）"
        existing = ov_memory.current_session(root)
        if existing:
            return f"会话记忆：复用会话 {existing}{tail}"
        started = ov_memory.begin(root)
        return f"会话记忆：已建会话 {started.get('session_id')}{tail}"
    except Exception:
        return ""


def main() -> None:
    payload = load_payload()
    root = project_root(payload)
    version = plugin_version()
    host = host_name()
    setup_cmd = command_hint("setup")
    review_cmd = command_hint("review")
    if root is None:
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": (
                        f"knowledge-base-plugin v{version} 已加载（{host}）。当前项目未初始化："
                        f"运行 {setup_cmd} 建立 .kb 知识库运行时。"
                    ),
                }
            }
        )
        return
    try:
        state = context.load_state(root)
        audit_state = state.get("last_audit") or {}
        publish_state = state.get("last_publish") or {}
        pending = proposals.pending_proposals(root)
        lines = [
            f"knowledge-base-plugin v{version}（{host}，mode={context.load_config(root).get('mode')}）",
            f"domain={state.get('domain')} last_audit={audit_state.get('audit_id')} passed={audit_state.get('passed')} last_publish={publish_state.get('version')}",
        ]
        if pending:
            lines.append(
                f"⚠ {len(pending)} 条规则处于 APPLIED/READY_FOR_REVIEW 中间态，等待 Owner 终签：{review_cmd}"
            )
        note = _memory_note(root)
        if note:
            lines.append(note)
        emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(lines)}})
    except Exception:
        emit({})


if __name__ == "__main__":
    main()
