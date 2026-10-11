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
"""PreToolUse hook：kb_publish_guard / audit_completion_guard / rules 直改拦截。"""

from __future__ import annotations

from common import emit, fail_open, load_payload, project_root, trace_payload  # noqa: E402

# 引擎是惰性导入的：某些机器上"python 启动 + 导入引擎"要 20 秒左右，而宿主 hook 有超时，
# 超时会被当作 fail-open 放行。不相关的工具走快速通道，只有需要门控的才付这份成本。
_GATED_TOOLS = {
    "bash", "task", "executecommand", "cli",
    "exec_command", "local_shell", "shell_command", "shell",
    "write", "edit", "multiedit", "notebookedit",
    "apply_patch", "applypatch", "patch", "edit_file", "write_file",
}
_GATED_SUBSTRINGS = ("kbp", "kb-publish", "openviking", "viking", "data-quality-kb")


def _needs_gate(tool_name: str) -> bool:
    lowered = tool_name.lower()
    return lowered in _GATED_TOOLS or any(part in lowered for part in _GATED_SUBSTRINGS)


def block_output(decision) -> dict:
    """宿主 hook 输出 schema 是 additionalProperties:false：只允许下面这几个键。

    多写字段（例如 permissionDecisionDetails / shouldBlock）会让宿主把整条输出判为非法
    并静默放行——实测踩过，所以这里严格贴 schema，并用 exit 0 + JSON 决策表达阻断。
    """
    message = f"[knowledge-base-plugin:{decision.gate}] {decision.reason}"
    return {
        "decision": "block",
        "reason": message,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        },
    }


def main() -> None:
    payload = load_payload()
    trace_payload("PreToolUse", payload)
    tool_name = str(payload.get("tool_name") or payload.get("tool") or "")
    if not _needs_gate(tool_name):
        emit({})
        return
    root = project_root(payload)
    from core import gates  # 惰性导入

    try:
        decision = gates.decide_pre_tool(payload, root)
    except Exception as exc:
        fail_open(f"{type(exc).__name__}: {exc}")
        return
    if decision.blocked():
        emit(block_output(decision), exit_code=0)
    emit({})


if __name__ == "__main__":
    main()
