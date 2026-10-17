# Copyright 2026 AI实战技能圈
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""自动捕获 / 召回（对齐 OpenViking 官方 Codex 插件）的端到端测试。

用标准库起一个假 OpenViking 服务端（实现 sessions / messages / commit / search），
不依赖外网，也不碰真实实例。覆盖：transcript 解析、水位去重、阈值提交、
召回文本块、四个 hook 的输入输出 schema、服务不可达时的 fail-open、空闲清扫。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_REPO / "engine"))

from core import context, ov_memory  # noqa: E402


class FakeOpenViking:
    """最小可用的 OV 服务端：会话、消息、提交、检索。"""

    def __init__(self) -> None:
        self.sessions: dict = {}
        self.requests: list = []
        self.search_items: list = [
            {"uri": "viking://user/default/memories/preferences/sql.md",
             "abstract": "SQL 一律 4 空格缩进；user_id 是 STRING。"}
        ]
        self.fail_search = False
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # noqa: D401 - 静默
                return

            def _json(self, code: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                if not length:
                    return {}
                try:
                    return json.loads(self.rfile.read(length).decode("utf-8"))
                except json.JSONDecodeError:
                    return {}

            def _record(self, body) -> None:
                fake.requests.append((self.command, self.path, body))

            def do_GET(self) -> None:  # noqa: N802
                self._record(None)
                path = urllib.parse.urlsplit(self.path).path
                parts = [p for p in path.split("/") if p]
                if path in ("/health", "/ready"):
                    self._json(200, {"status": "ok", "result": {"status": "ok", "healthy": True}})
                    return
                if len(parts) == 4 and parts[:3] == ["api", "v1", "sessions"]:
                    session = fake.sessions.get(parts[3])
                    if session is None:
                        self._json(404, {"status": "error", "error": {"code": "NOT_FOUND", "message": "no session"}})
                        return
                    self._json(200, {"status": "ok", "result": {
                        "session_id": parts[3],
                        "total_message_count": len(session["messages"]),
                        "pending_tokens": session["pending_tokens"],
                        "commit_count": len(session["commits"]),
                    }})
                    return
                self._json(404, {"status": "error", "error": {"code": "NOT_FOUND", "message": path}})

            def do_POST(self) -> None:  # noqa: N802
                body = self._body()
                self._record(body)
                path = urllib.parse.urlsplit(self.path).path
                parts = [p for p in path.split("/") if p]
                if parts == ["api", "v1", "sessions"]:
                    sid = str(body.get("session_id") or "s-" + str(len(fake.sessions) + 1))
                    fake.sessions.setdefault(sid, {"messages": [], "pending_tokens": 0, "commits": []})
                    self._json(200, {"status": "ok", "result": {"session_id": sid}})
                    return
                if len(parts) >= 4 and parts[:3] == ["api", "v1", "sessions"]:
                    sid, action = parts[3], parts[4] if len(parts) > 4 else ""
                    session = fake.sessions.setdefault(sid, {"messages": [], "pending_tokens": 0, "commits": []})
                    if len(parts) == 6 and action == "messages" and parts[5] == "batch":
                        batch = body.get("messages") or []
                        session["messages"].extend(batch)
                        session["pending_tokens"] += 10 * len(batch)
                        self._json(200, {"status": "ok", "result": {"added": len(batch)}})
                        return
                    if len(parts) == 5 and action == "messages":
                        session["messages"].append(body)
                        session["pending_tokens"] += 10
                        self._json(200, {"status": "ok", "result": {"added": 1}})
                        return
                    if len(parts) == 5 and action == "commit":
                        session["commits"].append(body)
                        session["pending_tokens"] = 0
                        self._json(200, {"status": "ok", "result": {
                            "session_id": sid, "status": "accepted", "task_id": "task-1", "archived": True,
                        }})
                        return
                if path in ("/api/v1/search/search", "/api/v1/search/find"):
                    if fake.fail_search:
                        self._json(500, {"status": "error", "error": {"code": "INTERNAL", "message": "boom"}})
                        return
                    self._json(200, {"status": "ok", "result": {"memories": fake.search_items}})
                    return
                self._json(404, {"status": "error", "error": {"code": "NOT_FOUND", "message": path}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class MemoryHookBase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeOpenViking()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        context.ensure_app_dir(self.root, mode="mock", domain="user")
        cfg = context.load_config(self.root)
        cfg["ov"].update({
            "url": self.fake.url,
            "memory_enabled": True,
            "remote_enabled": True,
            "auto_capture": True,
            "auto_recall": True,
            "commit_token_threshold": 20,
            "recall_limit": 3,
            "recall_timeout_s": 2,
            "session_idle_ttl_minutes": 30,
        })
        context.write_json(context.config_path(self.root), cfg)
        self.transcript = self.root / "rollout.jsonl"

    def tearDown(self) -> None:
        self.fake.close()
        self._tmp.cleanup()

    def write_rollout(self, extra: bool = False) -> Path:
        lines = [
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                                                  "content": [{"type": "text", "text": "记住：user_id 是 STRING。"}]}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "{}"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                  "content": [{"type": "text", "text": "好的，已记下。"}]}},
        ]
        if extra:
            lines.append({"type": "event_msg", "payload": {"type": "user_message",
                                                           "message": "再加一条：SQL 用 4 空格缩进。"}})
        self.transcript.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
                                   encoding="utf-8")
        return self.transcript


class CaptureTests(MemoryHookBase):
    def test_parse_ignores_tool_calls(self) -> None:
        turns, ok = ov_memory.read_transcript_turns(self.write_rollout())
        self.assertTrue(ok)
        self.assertEqual(["user", "assistant"], [t["role"] for t in turns])

    def test_capture_advances_watermark_and_dedupes(self) -> None:
        first = ov_memory.capture_from_transcript(self.root, str(self.write_rollout()), "codex-1")
        self.assertEqual(2, first["added"])
        self.assertTrue(first["session_id"].startswith("cx-codex-1"))
        second = ov_memory.capture_from_transcript(self.root, str(self.write_rollout()), "codex-1")
        self.assertEqual(0, second["added"], "同一份 transcript 重复跑不应重复追加")
        stored = self.fake.sessions[first["session_id"]]["messages"]
        self.assertEqual(2, len(stored))

    def test_capture_commits_when_pending_tokens_cross_threshold(self) -> None:
        self.write_rollout()
        result = ov_memory.capture_from_transcript(self.root, str(self.transcript), "codex-2")
        self.assertTrue(result["commit"]["committed"], result)
        self.assertEqual(1, len(self.fake.sessions[result["session_id"]]["commits"]))

    def test_keyword_mode_skips_unrelated_turns(self) -> None:
        cfg = context.load_config(self.root)
        cfg["ov"]["capture_mode"] = "keyword"
        context.write_json(context.config_path(self.root), cfg)
        self.write_rollout()
        plain = self.root / "plain.jsonl"
        plain.write_text(json.dumps({"type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [{"type": "text", "text": "今天天气不错"}]}},
            ensure_ascii=False), encoding="utf-8")
        result = ov_memory.capture_from_transcript(self.root, str(plain), "codex-3")
        self.assertEqual(0, result["added"])
        self.assertEqual("keyword", result["skipped"])


class RecallTests(MemoryHookBase):
    def test_recall_block_contains_uri_and_text(self) -> None:
        block = ov_memory.recall_block(self.root, "user_id 是什么类型？")
        self.assertIn("viking://user/", block)
        self.assertIn("STRING", block)
        self.assertIn("<openviking-memory>", block)

    def test_recall_empty_when_no_hits(self) -> None:
        self.fake.search_items = []
        self.assertEqual("", ov_memory.recall_block(self.root, "没有任何命中"))


class HookContractTests(MemoryHookBase):
    def run_hook(self, name: str, payload: dict) -> tuple:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, str(ROOT_REPO / "hooks" / name)],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, cwd=str(ROOT_REPO),
        )
        return proc, json.loads(proc.stdout.strip() or "{}")

    def test_user_prompt_submit_injects_context(self) -> None:
        proc, out = self.run_hook("userpromptsubmit.py", {
            "prompt": "user_id 是什么类型？", "session_id": "codex-hook-1", "cwd": str(self.root),
        })
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual("UserPromptSubmit", out.get("hookSpecificOutput", {}).get("hookEventName"))
        self.assertIn("STRING", out["hookSpecificOutput"]["additionalContext"])

    def test_stop_appends_turn_and_returns_empty(self) -> None:
        self.write_rollout()
        proc, out = self.run_hook("stop.py", {
            "session_id": "codex-hook-2", "transcript_path": str(self.transcript), "cwd": str(self.root),
        })
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual({}, out)
        self.assertEqual(2, len(self.fake.sessions["cx-codex-hook-2"]["messages"]))

    def test_pre_compact_commits(self) -> None:
        self.write_rollout()
        proc, out = self.run_hook("precompact.py", {
            "session_id": "codex-hook-3", "transcript_path": str(self.transcript), "cwd": str(self.root),
        })
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual({}, out)
        self.assertEqual(1, len(self.fake.sessions["cx-codex-hook-3"]["commits"]))

    def test_recall_fails_open_when_server_is_down(self) -> None:
        cfg = context.load_config(self.root)
        cfg["ov"]["url"] = "http://127.0.0.1:9"
        cfg["ov"]["recall_timeout_s"] = 1
        context.write_json(context.config_path(self.root), cfg)
        started = time.time()
        proc, out = self.run_hook("userpromptsubmit.py", {
            "prompt": "user_id 是什么类型？", "session_id": "codex-hook-4", "cwd": str(self.root),
        })
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual({}, out)
        self.assertLess(time.time() - started, 10)


class SweepTests(MemoryHookBase):
    def test_idle_session_is_captured_and_committed(self) -> None:
        self.write_rollout()
        state = ov_memory.load_host_state(self.root)
        state["sessions"]["codex-old"] = {
            "ov_session_id": "cx-codex-old",
            "captured_turn_count": 0,
            "capture_format_version": 1,
            "transcript_path": str(self.transcript),
            "created_at": "2026-01-01T00:00:00Z",
            "last_capture_at": "2026-01-01T00:00:00Z",
        }
        ov_memory.save_host_state(self.root, state)
        result = ov_memory.sweep_idle_sessions(self.root)
        self.assertEqual(1, len(result["swept"]))
        self.assertEqual(1, len(self.fake.sessions["cx-codex-old"]["commits"]))


if __name__ == "__main__":
    unittest.main()
