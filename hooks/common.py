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
"""Shared helpers for knowledge-base-plugin hooks (fail-open by design)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parent.parent)
ENGINE_DIR = PLUGIN_ROOT / "engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))


def load_payload() -> Dict[str, Any]:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def trace_payload(event: str, payload: Dict[str, Any]) -> None:
    """把原始 hook payload 追加到 ``$DDP_HOOK_TRACE``（默认关闭）。

    排查宿主差异用：Windows 设 ``$env:DDP_HOOK_TRACE="C:\\temp\\kb-hook.jsonl"``
    后再启动宿主，就能看到两个宿主各自发来的工具名与参数形状。
    """
    target = os.environ.get("DDP_HOOK_TRACE", "").strip()
    if not target:
        return
    try:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": event, "payload": payload}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def plugin_version() -> str:
    """从插件清单读版本号，避免在 hook 里写死（曾出现消息里写死 v1.0.0）。"""
    for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        path = PLUGIN_ROOT / rel
        if path.is_file():
            try:
                version = json.loads(path.read_text(encoding="utf-8")).get("version")
                if version:
                    return str(version)
            except Exception:
                continue
    return "unknown"


def host_name() -> str:
    """Codex 会注入 PLUGIN_DATA；Claude Code 不会。"""
    return "Codex" if os.environ.get("PLUGIN_DATA") else "Claude Code"


def command_hint(name: str) -> str:
    """Codex 用技能名（kbp- 前缀，避免与 kb-publish/kb-audit 方法论技能撞名），
    Claude Code 用斜杠命令。"""
    return f"kbp-{name}" if os.environ.get("PLUGIN_DATA") else f"/kb-{name}"


def project_root(payload: Dict[str, Any]) -> Optional[Path]:
    from core import context

    cwd_value = payload.get("cwd")
    start = Path(cwd_value) if cwd_value and Path(cwd_value).is_dir() else Path.cwd()
    return context.project_root(start)


def emit(obj: Any, exit_code: int = 0) -> None:
    """写给宿主的 hook 决策：ASCII 转义，避免 Windows cp936 与宿主 UTF-8 不匹配导致乱码。"""
    try:
        sys.stdout.write(json.dumps(obj))
        sys.stdout.flush()
    except Exception:
        pass
    sys.exit(exit_code)


def fail_open(message: str) -> None:
    emit({"systemMessage": f"[knowledge-base-plugin] hook 内部错误（fail-open）: {message}"})
