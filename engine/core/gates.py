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
"""PreToolUse 门控：kb_publish_guard / audit_completion_guard / rules 直改拦截 / setup_guard。

与 data-development-plugin 同一模式：决策函数纯逻辑、可单测；hooks 只做薄封装。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import audit, context


@dataclass
class Decision:
    action: str  # allow | block
    gate: str = ""
    reason: str = ""
    notes: List[str] = field(default_factory=list)

    def blocked(self) -> bool:
        return self.action == "block"


ALLOW = Decision("allow")


# ── 知识库 CLI 识别：只认"真的在调用"，不做整条命令的子串匹配 ──────────────────
# 旧的子串实现（`re.search(r"kbp\.py|kb-publish|openviking|...", 整条命令)`）把两件
# 完全不同的东西混为一谈，实测被拦过两次：
#   1) `rg -n "^def verb_" engine/kbp.py`      —— 只读检索，路径里含 kbp.py
#   2) `"=== OpenViking 远程集成 ==="`          —— 只是打印一个词当标题
# 调用形态只有三种，其余一律不算：
#   * 段首就是引擎脚本：`kbp.py publish --domain user` / `./engine/kbp.py ...`
#   * 段首是 python 启动器且后面跟着引擎脚本：`py -3 .data-dev/engine/kbp.py publish`
#   * 段首是知识库/OV 的 CLI 可执行名：`kb-publish ...` / `ov sync ...`
ENGINE_SCRIPT = "kbp.py"
PYTHON_LAUNCHERS = ("py", "python", "python3", "python.exe", "pythonw.exe")
KB_CLI_NAMES = (
    "kb-publish",
    "kb-audit",
    "kb-sync",
    "kb-setup",
    "kb-review",
    "kb-generate",
    "kb-refresh",
    "kb-propose",
    "kb-status",
    "kb-overview",
    "data-quality-kb-maintain",
)
OV_CLI_NAMES = ("ov", "openviking", "viking")

_TOKEN_RE = re.compile(r'"[^"]*"|\'[^\']*\'|\S+')
_ENV_PREFIX_RE = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+")
_LAUNCHER_PREFIX_RE = re.compile(r"^(?:sudo|env|nohup|time|command|exec|start|call)\s+", re.IGNORECASE)


def _basename(token: str) -> str:
    return re.split(r"[/\\]", token.strip().strip("\"'"))[-1]


def kb_invocations(command: str) -> List[Dict[str, Any]]:
    """返回**真的在调用**知识库引擎/CLI 的命令段，每段给 ``head`` 与后续 ``args``。

    按 shell 分隔符切段后逐段看段首：段首不是启动器/CLI 名的段一律不算调用。
    """
    found: List[Dict[str, Any]] = []
    for raw in re.split(r";|&&|\|\||\n", command):
        text = _ENV_PREFIX_RE.sub("", raw.strip(), count=1)
        text = _LAUNCHER_PREFIX_RE.sub("", text, count=1)
        tokens = [t.strip("\"'") for t in _TOKEN_RE.findall(text)]
        if not tokens:
            continue
        head = _basename(tokens[0]).lower()
        args = [t.lower() for t in tokens[1:]]
        if head == ENGINE_SCRIPT or head in KB_CLI_NAMES or head in OV_CLI_NAMES:
            found.append({"head": head, "args": args})
        elif head in PYTHON_LAUNCHERS and any(
            _basename(t).lower() == ENGINE_SCRIPT for t in tokens[1:]
        ):
            found.append({"head": head, "args": args})
    return found


def analyze_command(command: str) -> Dict[str, Any]:
    invocations = kb_invocations(command)
    args: set = set()
    for invocation in invocations:
        args.update(invocation["args"])
    heads = {invocation["head"] for invocation in invocations}
    is_kb_cli = bool(invocations)
    return {
        "command": command,
        "lowered": command.lower(),
        "invocations": invocations,
        "is_kb_cli": is_kb_cli,
        "is_setup": is_kb_cli and ("setup" in args or "kb-setup" in heads),
        "is_audit": is_kb_cli and ("audit" in args or "kb-audit" in heads),
        "is_publish": is_kb_cli and ("publish" in args or "kb-publish" in heads),
        "is_sync": is_kb_cli
        and ("sync" in args or "kb-sync" in heads or bool(heads & set(OV_CLI_NAMES))),
    }


# 写文件动词表：覆盖 POSIX shell 与 PowerShell 的常见写法（含重定向）。
_MUTATOR_RE = re.compile(
    r"\b(rm|del|delete|unlink|remove|mv|move|rename|touch|write_text|write_bytes|remove-item|removeitem|shutil"
    r"|set-content|add-content|out-file|new-item|clear-content|copy-item|copy|cp|tee|tee-object|dd)\b"
    r"|sed\s+-i|open\([^)]*['\"]w"
    r"|(?<![-\d&])>>?(?!&)",
    re.IGNORECASE,
)

# 机器资产标记：只在"同一段里同时出现写动词"时才判违规
_SENSITIVE_MARKERS = (
    "_state.json",
    "_context.md",
    ".kb-audit",
    "runtime/",
    "runtime\\",
    "manifest.json",
)


def _command_segments(command: str) -> List[str]:
    """按 shell 分隔符切段（`;` / `&&` / `||` / 换行）：写动词与敏感路径必须同段才算命中。"""
    return [seg for seg in re.split(r";|&&|\|\||\n", command.lower()) if seg.strip()]


_VAR_ASSIGN_RE = re.compile(r"\$?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\n]+)")


def _expand_vars(segments: List[str]) -> List[str]:
    """把简单变量赋值展开到后续段（`$t = ...\\runtime\\x` 之后 `Set-Content -Path $t`）。"""
    values: Dict[str, str] = {}
    expanded_segments: List[str] = []
    for segment in segments:
        match = _VAR_ASSIGN_RE.search(segment)
        if match:
            values[match.group(1).lower()] = match.group(2)
        expanded = segment
        for name, value in values.items():
            expanded = re.sub(rf"\${re.escape(name)}\b", lambda _m, v=value: v, expanded)
        expanded_segments.append(expanded)
    return expanded_segments


def decide_cli_command(command: str, root: Optional[Path] = None) -> Decision:
    if not command.strip():
        return ALLOW
    root = root or context.project_root() or Path.cwd()
    analysis = analyze_command(command)
    lowered = analysis["lowered"]
    # 写动词与敏感路径必须落在**同一段**里才算命中（跨行分析脚本不该被误伤）
    segments = _expand_vars(_command_segments(command))
    inside_sensitive_dir = False
    for segment in segments:
        if re.search(r"(^|[;&|]\s*)cd\s", segment) and re.search(
            r"\.kb[/\\]+(runtime|\.runtime)([/\\]|\s|$)", segment
        ):
            inside_sensitive_dir = True
            continue
        if inside_sensitive_dir and _MUTATOR_RE.search(segment):
            return Decision(
                "block",
                gate="runtime_guard",
                reason="检测到先切入 .kb 机器资产目录、再用相对路径写入：按同一条硬门拦截。",
            )
        if ".kb" not in segment:
            continue
        marker = next((m for m in _SENSITIVE_MARKERS if m in segment), "")
        if not marker or not _MUTATOR_RE.search(segment):
            continue
        gate = "runtime_guard" if "runtime" in segment else "state_write_guard"
        return Decision(
            "block",
            gate=gate,
            reason=f"{gate}: .kb 下的状态/runtime/审计文件是机器资产，禁止在 Bash 中改写或 touch。",
        )

    # 同类绕过：shell 直接改 rules/（沉淀铁律：不直接手改，必走提案）
    for segment in segments:
        if not _MUTATOR_RE.search(segment):
            continue
        if not re.search(r"\.kb[\\/]+repo[\\/]+rules[\\/]", segment):
            continue
        return Decision(
            "block",
            gate="rules_direct_write_guard",
            reason="禁止通过 shell 直接改 rules/：沉淀铁律必走 data-quality-kb-maintain 提案（propose → 门禁 → Owner approve）。",
        )
    kb_root = context.project_root(root)
    if analysis["is_kb_cli"] and not analysis["is_setup"] and kb_root is None:
        return Decision("block", gate="setup_guard", reason="未初始化 .kb 知识库项目：先运行 /kb-setup。")
    if kb_root is None:
        return ALLOW
    if analysis["is_publish"]:
        gate = audit.audit_fresh_enough(kb_root)
        if not gate["ok"]:
            return Decision("block", gate="kb_publish_guard", reason=gate["reason"])
        if analysis["is_sync"]:
            return ALLOW
    # 即便不是 publish 关键词，只要是 OV/同步类工具且最近一次知识变更未审计，也提醒（软）
    if analysis["is_sync"] and not analysis["is_audit"]:
        gate = audit.audit_fresh_enough(kb_root)
        if not gate["ok"]:
            return Decision(
                "allow",
                gate="audit_completion_guard",
                reason=gate["reason"],
                notes=[f"audit_completion_guard: {gate['reason']}"],
            )
    return ALLOW


def _normalize_component(part: str) -> str:
    """归一化 Windows 路径分量：尾随点/空格会被文件系统忽略（`runtime.` == `runtime`）。"""
    if part in (".", "..", "/", "\\", ""):
        return part
    return part.rstrip(" .") or part


def decide_file_write(file_path: str, root: Optional[Path] = None) -> Decision:
    """直接手改 rules/ 一律拦截（沉淀铁律：不直接手改，必走提案）。"""
    if not file_path:
        return ALLOW
    root = root or Path.cwd()
    path = Path(file_path.strip())  # 尾随空格不能用来绕过名字匹配
    if not path.is_absolute():
        path = root / path
    try:
        # 归一化 . / .. 与软链接/junction：否则可以建一个指向 .kb/runtime 的链接绕过门控
        path = path.resolve()
    except OSError:
        path = path.absolute()
    name = _normalize_component(path.name).lower()  # 大写 + 尾随点/空格同样要命中
    parts = [_normalize_component(p).lower() for p in path.parts]
    for idx, part in enumerate(parts):
        if part == ".kb" and idx + 1 < len(parts):
            sibling = parts[idx + 1]
            if sibling == "runtime":
                return Decision("block", gate="runtime_guard", reason=".kb/runtime 是机器运行时目录，禁止工具写入。")
            if sibling == "_state.json":
                return Decision("block", gate="state_write_guard", reason="_state.json 是机器状态，只允许引擎写入。")
    if name.startswith(".kb-audit-") or name == ".kb-manifest.json":
        return Decision("block", gate="audit_manifest_guard", reason=f"{path.name} 是审计/发布留证，只允许引擎写入。")
    for idx, part in enumerate(parts):
        if part == ".kb" and idx + 2 < len(parts) and parts[idx + 1] == "repo" and parts[idx + 2] == "rules":
            return Decision(
                "block",
                gate="rules_direct_write_guard",
                reason=f"禁止直接手改 rules/: {path.name}。沉淀铁律：必走 data-quality-kb-maintain 提案（propose → 引擎门禁 → Owner approve）。",
            )
    return ALLOW


def _as_path_text(value: Any) -> str:
    """把宿主可能给出的各种"路径形态"取成字符串（list/dict/None 都能兜住）。"""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = next(iter(value.values()), "")
    return str(value or "").strip()


_MACHINE_ASSET_MARKERS = (
    ".kb/runtime",
    ".kb\\runtime",
    ".kb/_state.json",
    ".kb\\_state.json",
    ".kb/_context.md",
    ".kb\\.kb-audit",
    ".kb/.kb-audit",
    ".kb-manifest.json",
)


def _shape_fallback(tool_input: Any, root: Optional[Path]) -> Optional[Decision]:
    """形状兜底：工具名缺失/没见过时，只要载荷里有"写哪个文件/跑什么命令"的形状，照样过门。"""
    if isinstance(tool_input, dict):
        candidate = _as_path_text(
            tool_input.get("file_path") or tool_input.get("path") or tool_input.get("notebook_path")
        )
        if candidate:
            return decide_file_write(candidate, root)
        command = tool_input.get("command") or tool_input.get("cmd")
        if command:
            return decide_cli_command(str(command), root)
        return None
    text = str(tool_input or "").lower()
    if any(marker in text for marker in _MACHINE_ASSET_MARKERS):
        return Decision("block", gate="shape_guard", reason="载荷形状异常但提到机器资产，按保守策略拦截。")
    return None


def decide_pre_tool(payload: Dict[str, Any], root: Optional[Path] = None) -> Decision:
    """PreToolUse 分派：同时认 Claude Code 与 Codex 的工具名。

    Claude Code：``Bash`` / ``Write`` / ``Edit`` / ``MultiEdit``；
    Codex：``exec_command`` / ``local_shell`` / ``shell_command``（命令），
    ``apply_patch``（补丁式写文件，input 里是 ``*** Add File: <path>`` 形式的补丁文本）。
    """
    tool_name = str(payload.get("tool_name") or "")
    raw_input = payload.get("tool_input") or {}
    shape_anomaly = not isinstance(raw_input, dict)
    tool_input = {"command": str(raw_input)} if shape_anomaly else raw_input
    if shape_anomaly:
        fallback = _shape_fallback(raw_input, root)
        if fallback is not None:
            return fallback
    lowered_tool = tool_name.lower()
    if tool_name in ("Bash", "Task", "ExecuteCommand", "CLI") or lowered_tool in (
        "exec_command",
        "local_shell",
        "shell_command",
        "shell",
    ):
        return decide_cli_command(str(tool_input.get("command") or tool_input.get("cmd") or ""), root)
    if lowered_tool in ("apply_patch", "applypatch", "patch", "write_file", "edit_file"):
        patch_text = str(
            tool_input.get("patch")
            or tool_input.get("input")
            or tool_input.get("content")
            or tool_input.get("text")
            or tool_input.get("command")  # Codex 实测：补丁文本放在 tool_input["command"]
            or ""
        )
        targets: List[str] = _patch_targets(patch_text)
        if not targets and tool_input:
            targets = _patch_targets(json.dumps(tool_input, ensure_ascii=False))
        for target in targets:
            decision = decide_file_write(target, root)
            if decision.blocked():
                return decision
        return ALLOW
    if tool_name in ("Write", "Edit", "MultiEdit"):
        return decide_file_write(
            _as_path_text(tool_input.get("file_path") or tool_input.get("path") or ""), root
        )
    fallback = _shape_fallback(tool_input, root)
    return fallback if fallback is not None else ALLOW


_PATCH_TARGET_RE = re.compile(
    r"^\*\*\*\s+(?:Add|Update|Delete)\s+File:\s*(.+?)\s*$"  # *** Add File: <path>
    r"|^\*\*\*\s+Move to:\s*(.+?)\s*$",                      # *** Move to: <path>
    re.MULTILINE,
)


def _patch_targets(patch_text: str) -> List[str]:
    """抽出补丁里涉及的每个文件路径（含 ``*** Move to:`` 目标）。"""
    if not patch_text:
        return []
    targets = [(m.group(1) or m.group(2) or "").strip() for m in _PATCH_TARGET_RE.finditer(patch_text)]
    for line in patch_text.splitlines():
        if line.startswith("+++ b/"):
            targets.append(line[6:].strip())
    seen: List[str] = []
    for item in targets:
        if item and item not in seen:
            seen.append(item)
    return seen


def status_notes(root: Optional[Path]) -> str:
    if root is None:
        return ""
    try:
        state = context.load_state(root)
        audit_state = state.get("last_audit") or {}
        publish_state = state.get("last_publish") or {}
        return (
            f"domain={state.get('domain')} last_audit={audit_state.get('audit_id')} passed={audit_state.get('passed')} "
            f"last_publish={publish_state.get('version')}"
        )
    except Exception:
        return ""
