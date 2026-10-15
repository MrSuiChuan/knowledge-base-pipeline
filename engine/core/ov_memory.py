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
"""会话记忆：把一次会话记进 OpenViking，并在结束时触发记忆抽取。

**为什么单独一层**：本插件原先只把"定稿知识"写进 ``viking://resources/``
（见 ``ov_remote`` 与 ``sync.publish``）——那是**成品**。OpenViking 还有一条**记忆**链路：
会话 → 追加消息 → ``commit`` → 后台抽取记忆，落进 ``user/<id>/memories`` 与
``agent/<id>/memories``。两条路互不替代：一个记"这个仓库的事实"，一个记"这次会话里发生了什么"。

接口与字段取自服务端路由定义（本机已安装的 openviking 0.3.24，``server/routers/sessions.py``）：

======================  =========================================================
POST /api/v1/sessions                     建会话（可自带 session_id）
POST /api/v1/sessions/{id}/messages       追加一条（``role`` + ``content`` 或 ``parts``）
POST /api/v1/sessions/{id}/messages/batch 批量追加（服务端上限 100 条/次）
POST /api/v1/sessions/{id}/commit         归档 + **后台**抽取记忆，返回 ``task_id``
POST /api/v1/sessions/{id}/extract        只抽取、不归档
POST /api/v1/sessions/{id}/used           记录"这次用到了哪些上下文/技能"
GET  /api/v1/sessions/{id}                回读（``message_count`` / ``memories_extracted``）
GET  /api/v1/tasks/{task_id}              轮询后台任务
======================  =========================================================

**成本边界（必须说清）**：``commit`` 会触发 LLM 记忆抽取，走使用者在 ``ov.conf`` 里配的
embedding / vlm 配额。所以本模块默认**只提交不等待**由调用方决定；真正的抽取要不要跑，
由使用者拍板（见 docs/session-memory.md）。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import context, ov_remote

SESSIONS_PATH = "/api/v1/sessions"
TASKS_PATH = "/api/v1/tasks"

# 服务端 BatchAddMessageRequest 的硬上限（messages: List[..., max_length=100]）。
MAX_BATCH = 100

# 后台任务算"跑完了"的状态。服务端实现里出现过 completed / failed 两类；
# 这里放宽成集合，遇到没见过的状态就按"还没完"处理，最后由超时兜底报错。
TERMINAL_TASK_STATES = {
    "completed",
    "complete",
    "succeeded",
    "success",
    "done",
    "finished",
    "failed",
    "error",
    "cancelled",
    "canceled",
}
FAILED_TASK_STATES = {"failed", "error", "cancelled", "canceled"}


class MemoryError(RuntimeError):
    """会话记忆链路的失败。``gate`` 直接进机器的门控键，与其它模块保持同一形状。"""

    def __init__(self, gate: str, reason: str, **extra: Any) -> None:
        super().__init__(reason)
        self.gate = gate
        self.reason = reason
        self.extra = extra

    def payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"ok": False, "blocked": True, "gate": self.gate, "reason": self.reason}
        payload.update(self.extra)
        return payload


# --------------------------------------------------------------------------------------
# 配置与本地状态
# --------------------------------------------------------------------------------------


def memory_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """复用 ``ov_remote.resolve_settings`` 的传输与密钥来源，再叠加记忆开关。

    不新开第二套密钥读取路径：密钥仍然只来自环境变量或 ``ov.api_key_file``。
    """
    settings = ov_remote.resolve_settings(config)
    ov = config.get("ov") or {}
    settings["enabled"] = bool(ov.get("memory_enabled", False))
    try:
        settings["keep_recent_count"] = int(ov.get("keep_recent_count", 10))
    except (TypeError, ValueError):
        settings["keep_recent_count"] = 10
    try:
        settings["task_timeout"] = float(ov.get("task_timeout", 180))
    except (TypeError, ValueError):
        settings["task_timeout"] = 180.0
    return settings


DISABLED_REASON = (
    "会话记忆未启用：在 .kb/config.json 的 ov 段设 \"memory_enabled\": true 后再试"
    "（抽取会消耗模型配额，详见 docs/session-memory.md）"
)


def disabled_error() -> "MemoryError":
    return MemoryError("memory_disabled", DISABLED_REASON)


def require_enabled(settings: Dict[str, Any]) -> Dict[str, Any]:
    if not settings.get("enabled"):
        raise disabled_error()
    return settings


def is_enabled(config: Dict[str, Any]) -> bool:
    """只读「开没开」这一步，不解析传输与密钥来源。"""
    ov = config.get("ov") if isinstance(config.get("ov"), dict) else {}
    return bool(ov.get("memory_enabled", False))


def state_dir(root: Path) -> Path:
    return context.runtime_dir(root) / "memory"


def state_path(root: Path) -> Path:
    return state_dir(root) / "session.json"


def load_state(root: Path) -> Dict[str, Any]:
    return context.load_json(state_path(root), {}) or {}


def save_state(root: Path, state: Dict[str, Any]) -> Path:
    path = state_path(root)
    context.write_json(path, state)
    return path


def current_session(root: Path) -> Optional[str]:
    return str(load_state(root).get("session_id") or "") or None


# --------------------------------------------------------------------------------------
# 客户端
# --------------------------------------------------------------------------------------


class MemoryClient(ov_remote.RemoteClient):
    """会话与记忆的 HTTP 客户端。传输层直接复用 ``RemoteClient``（含密钥、账号头、错误解析）。"""

    # ---------------------------------------------------------------- 会话
    def create_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if session_id:
            body["session_id"] = session_id
        result = self.request("POST", SESSIONS_PATH, body=body)
        return result if isinstance(result, dict) else {"raw": result}

    def get_session(self, session_id: str) -> Dict[str, Any]:
        result = self.request("GET", f"{SESSIONS_PATH}/{session_id}")
        return result if isinstance(result, dict) else {"raw": result}

    def add_message(self, session_id: str, role: str, content: str, role_id: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"role": role, "content": content}
        if role_id:
            body["role_id"] = role_id
        result = self.request("POST", f"{SESSIONS_PATH}/{session_id}/messages", body=body)
        return result if isinstance(result, dict) else {"raw": result}

    def add_messages(self, session_id: str, messages: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        """批量追加；按服务端上限自动分批，返回每批的结果与总数。"""
        pending: List[Dict[str, Any]] = [dict(m) for m in messages]
        if not pending:
            raise MemoryError("memory_empty_batch", "批量追加的消息列表是空的")
        batches: List[Dict[str, Any]] = []
        for start in range(0, len(pending), MAX_BATCH):
            chunk = pending[start : start + MAX_BATCH]
            result = self.request(
                "POST", f"{SESSIONS_PATH}/{session_id}/messages/batch", body={"messages": chunk}
            )
            batches.append(result if isinstance(result, dict) else {"raw": result})
        return {"session_id": session_id, "added": len(pending), "batches": len(batches), "results": batches}

    def commit(self, session_id: str, keep_recent_count: Optional[int] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if keep_recent_count is not None:
            body["keep_recent_count"] = int(keep_recent_count)
        result = self.request("POST", f"{SESSIONS_PATH}/{session_id}/commit", body=body)
        return result if isinstance(result, dict) else {"raw": result}

    def extract(self, session_id: str) -> Dict[str, Any]:
        result = self.request("POST", f"{SESSIONS_PATH}/{session_id}/extract")
        return result if isinstance(result, dict) else {"raw": result}

    def record_used(self, session_id: str, contexts: Optional[List[str]] = None, skill: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if contexts:
            body["contexts"] = list(contexts)
        if skill:
            body["skill"] = dict(skill)
        if not body:
            raise MemoryError("memory_empty_used", "record_used 至少要给 contexts 或 skill 之一")
        result = self.request("POST", f"{SESSIONS_PATH}/{session_id}/used", body=body)
        return result if isinstance(result, dict) else {"raw": result}

    # ---------------------------------------------------------------- 任务
    def get_task(self, task_id: str) -> Dict[str, Any]:
        result = self.request("GET", f"{TASKS_PATH}/{task_id}")
        return result if isinstance(result, dict) else {"raw": result}

    def check_ready(self) -> Dict[str, Any]:
        """就绪探针（``GET /ready``）：不通就别提交。

        2026-10-11 实测的教训：目的地实例的 embedding 端点不可用时（余额 402 / 鉴权失败 /
        provider 挂掉），``commit`` 照样返回 ``accepted``、后台任务照样 ``completed``，
        但抽取结果是 0 条——**白提交一次，还留下一份"看起来成功"的留证**。
        ``/ready`` 会如实报出来（失败时非 2xx，payload 里 checks.embedding 看得出来）。
        """
        try:
            raw, status = self._send("GET", "/ready")
        except ov_remote.OVRemoteError as exc:
            return {"ok": False, "http_status": exc.http_status, "reason": exc.message, "payload": exc.to_dict()}
        return {"ok": status < 400, "http_status": status, "payload": ov_remote._json_or_text(raw)}

    def wait_task(self, task_id: str, timeout: Optional[float] = None, interval: float = 2.0) -> Dict[str, Any]:
        """轮询到终态。超时如实报超时——不把"没等到"写成"成功"。"""
        limit = float(timeout if timeout is not None else getattr(self, "timeout", 180.0))
        deadline = time.monotonic() + limit
        last: Dict[str, Any] = {}
        while True:
            last = self.get_task(task_id)
            status = str(last.get("status") or last.get("state") or "").lower()
            if status in TERMINAL_TASK_STATES:
                last["_terminal"] = True
                last["_failed"] = status in FAILED_TASK_STATES
                return last
            if time.monotonic() >= deadline:
                raise MemoryError(
                    "memory_task_timeout",
                    f"记忆抽取任务 {task_id} 在 {limit:.0f}s 内没到终态（最后状态：{status or 'unknown'}）；"
                    "任务仍在后台跑，可用 memory status --task 再查",
                    task_id=task_id,
                    last_status=status,
                )
            time.sleep(interval)


def client_for(root: Path) -> "MemoryClient":
    """按项目配置建客户端；未启用 / 配置缺失都在这里拦下。

    判断顺序有意为之：先「开没开」，再「地址密钥齐不齐」。
    关着记忆的用户最先该看到的是「没启用」，而不是缺 ov.url 或「先跑 memory begin」
    ——后两条都把人指向错误动作（2026-10-14 测试用例 K-22）。
    """
    config = context.load_config(root)
    if not is_enabled(config):
        raise disabled_error()
    settings = memory_settings(config)
    return MemoryClient(settings)


# --------------------------------------------------------------------------------------
# 面向命令层的高层动作（都带留证）
# --------------------------------------------------------------------------------------


def begin(root: Path, session_id: Optional[str] = None, client: Optional[MemoryClient] = None) -> Dict[str, Any]:
    """建会话并把它记进 .kb/runtime/memory/session.json。"""
    client = client or client_for(root)
    created = client.create_session(session_id)
    resolved = str(created.get("session_id") or session_id or "").strip()
    if not resolved:
        raise MemoryError("memory_no_session_id", f"服务端没返回 session_id：{created}", raw=created)
    state = load_state(root)
    state.update(
        {
            "session_id": resolved,
            "created_at": state.get("created_at") or context.utcnow(),
            "updated_at": context.utcnow(),
            "add_count": 0,
            "commits": state.get("commits") or [],
        }
    )
    save_state(root, state)
    return {"ok": True, "session_id": resolved, "state": str(state_path(root)), "server": created}


def append(root: Path, role: str, content: str, client: Optional[MemoryClient] = None) -> Dict[str, Any]:
    # 先解析配置（未启用 / 缺地址在这里就报），再判会话：否则关着记忆的用户
    # 会先被告知"先跑 memory begin"，而 begin 又会回一句"没启用"——门指错了方向。
    client = client or client_for(root)
    session_id = current_session(root)
    if not session_id:
        raise MemoryError("memory_no_session", "还没有绑定会话：先跑 kbp.py memory begin")
    result = client.add_message(session_id, role, content)
    state = load_state(root)
    state["add_count"] = int(state.get("add_count") or 0) + 1
    state["updated_at"] = context.utcnow()
    save_state(root, state)
    return {"ok": True, "session_id": session_id, "role": role, "chars": len(content or ""), "server": result}


def append_many(root: Path, messages: List[Dict[str, Any]], client: Optional[MemoryClient] = None) -> Dict[str, Any]:
    client = client or client_for(root)
    session_id = current_session(root)
    if not session_id:
        raise MemoryError("memory_no_session", "还没有绑定会话：先跑 kbp.py memory begin")
    result = client.add_messages(session_id, messages)
    state = load_state(root)
    state["add_count"] = int(state.get("add_count") or 0) + len(messages)
    state["updated_at"] = context.utcnow()
    save_state(root, state)
    result["ok"] = True
    return result


def extraction_summary(task: Dict[str, Any]) -> Dict[str, Any]:
    """把提交任务译成"到底抽出来没有"，而不是只看任务状态。

    2026-10-11 实测：模型配额不足（MiniMax 402 insufficient balance）时，
    服务端日志写着 ``Extracted 0 memories``、embedding 连续失败触发熔断，
    但任务的 ``status`` 仍是 ``completed``。只看 status 就会把"抽取失败"报成"抽取成功"——
    那是留证撒谎，本仓库不接受。所以这里再看两个信号：抽出的条目数、以及 LLM 用量。
    """
    result = task.get("result") or {}
    extracted = result.get("memories_extracted") or {}
    if isinstance(extracted, dict):
        total = sum(int(v or 0) for v in extracted.values() if isinstance(v, (int, float)))
    else:
        total = 0
    usage = ((result.get("token_usage") or {}).get("llm")) or {}
    llm_tokens = int(usage.get("total_tokens") or 0)
    summary: Dict[str, Any] = {
        "task_ok": not bool(task.get("_failed")),
        "memories_extracted": extracted,
        "memories_total": total,
        "llm_tokens": llm_tokens,
    }
    if summary["task_ok"] and total == 0:
        summary["extraction_note"] = (
            "任务完成但没有产出记忆、且 LLM 用量为 0：可能是本次会话确实没有可抽取的内容，"
            "也可能是模型调用失败（例如配额/余额不足）。请查服务端日志确认，"
            "不要默认当成抽取成功。"
        )
    return summary


def commit(
    root: Path,
    keep_recent_count: Optional[int] = None,
    wait: bool = True,
    client: Optional[MemoryClient] = None,
) -> Dict[str, Any]:
    """归档 + 触发记忆抽取。留证写进 .kb/runtime/memory/commit-<ts>.json。"""
    client = client or client_for(root)
    session_id = current_session(root)
    if not session_id:
        raise MemoryError("memory_no_session", "还没有绑定会话：先跑 kbp.py memory begin")
    if keep_recent_count is None:
        keep_recent_count = int(getattr(client, "keep_recent_count", 0) or 0)
    readiness = client.check_ready()
    if not readiness.get("ok"):
        raise MemoryError(
            "memory_not_ready",
            "目标实例未就绪（/ready 未通过）：现在提交会白提交——通常是 embedding/模型端点不可用"
            "（余额不足、鉴权失败、provider 挂掉）。先修端点再用 kbp.py ov-check 自检，然后重跑 commit。",
            server=str(getattr(client, "base_url", "")),
            ready=readiness,
        )
    result = client.commit(session_id, keep_recent_count=keep_recent_count)
    task_id = str(result.get("task_id") or "").strip()
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "keep_recent_count": keep_recent_count,
        "committed_at": context.utcnow(),
        "commit_result": result,
        "task_id": task_id,
        "task": None,
    }
    path = state_dir(root) / f"commit-{context.utcnow().replace(':', '')}.json"
    wait_error: Optional[MemoryError] = None
    if wait and task_id:
        try:
            task = client.wait_task(task_id)
            payload["task"] = task
            payload.update(extraction_summary(task))
        except MemoryError as exc:
            # 归档与抽取都已经在服务端触发（commit 成功、task_id 到手），
            # 只是没等到终态。留证必须先落盘——否则"提交过"这件事会凭空消失。
            wait_error = exc
            payload["wait_error"] = exc.reason
            payload["task_ok"] = None
    context.write_json(path, payload)
    state = load_state(root)
    state.setdefault("commits", []).append(
        {"at": payload["committed_at"], "task_id": task_id, "waited": bool(wait and task_id)}
    )
    state["updated_at"] = context.utcnow()
    save_state(root, state)
    if wait_error is not None:
        raise MemoryError(wait_error.gate, wait_error.reason, evidence=str(path), **wait_error.extra)
    return {
        "ok": True,
        "session_id": session_id,
        "task_id": task_id,
        "waited": bool(wait and task_id),
        "task_status": (payload.get("task") or {}).get("status"),
        "task_ok": payload.get("task_ok"),
        "memories_total": payload.get("memories_total"),
        "llm_tokens": payload.get("llm_tokens"),
        "extraction_note": payload.get("extraction_note"),
        "evidence": str(path),
    }


def status(root: Path, client: Optional[MemoryClient] = None) -> Dict[str, Any]:
    """回读服务端会话状态（message_count / memories_extracted）。"""
    client = client or client_for(root)
    session_id = current_session(root)
    if not session_id:
        raise MemoryError("memory_no_session", "还没有绑定会话：先跑 kbp.py memory begin")
    server = client.get_session(session_id)
    state = load_state(root)
    return {
        "ok": True,
        "session_id": session_id,
        "local_add_count": int(state.get("add_count") or 0),
        "local_commits": len(state.get("commits") or []),
        "server_message_count": server.get("message_count"),
        "memories_extracted": server.get("memories_extracted"),
        "server": server,
    }


def mark_used(
    root: Path,
    contexts: Optional[List[str]] = None,
    skill: Optional[Dict[str, Any]] = None,
    client: Optional[MemoryClient] = None,
) -> Dict[str, Any]:
    client = client or client_for(root)
    session_id = current_session(root)
    if not session_id:
        raise MemoryError("memory_no_session", "还没有绑定会话：先跑 kbp.py memory begin")
    result = client.record_used(session_id, contexts=contexts, skill=skill)
    return {"ok": True, "session_id": session_id, "server": result}
