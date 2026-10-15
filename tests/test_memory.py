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
"""会话记忆（ov_memory）：请求形状、分批、留证，以及几种「安静失败」。HTTP 全部桩掉。"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_REPO / "engine"))
sys.path.insert(0, str(ROOT_REPO / "hooks"))

from core import context, ov_memory, ov_remote  # noqa: E402


class FakeTransport:
    """把 ``request()`` 换掉：记下每次调用，按前缀返回预置结果。"""

    def __init__(self, responses: dict | None = None) -> None:
        self.calls: list = []
        self.responses = responses or {}

    def __call__(self, method: str, path: str, **kwargs):
        self.calls.append({"method": method, "path": path, **kwargs})
        for prefix, result in self.responses.items():
            if prefix in path:
                if isinstance(result, Exception):
                    raise result
                return result
        if path == "/api/v1/sessions":
            return {"session_id": "s-test-1"}
        if path.endswith("/messages/batch"):
            return {"added": len(kwargs.get("body", {}).get("messages", []))}
        if path.endswith("/messages"):
            return {"message_id": f"m{len(self.calls)}"}
        if path.endswith("/commit"):
            return {"session_id": "s-test-1", "status": "ok", "task_id": "t-test-1"}
        if path.startswith("/api/v1/tasks/"):
            return {"task_id": "t-test-1", "status": "completed"}
        if path.endswith("/used"):
            return {"recorded": True}
        if path.startswith("/api/v1/sessions/"):
            return {"session_id": "s-test-1", "message_count": 3, "memories_extracted": {"total": 2}}
        return {}


class MemoryBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        context.ensure_app_dir(self.root, mode="live", domain="user")
        cfg = context.load_config(self.root)
        cfg["ov"].update({"url": "http://127.0.0.1:1933", "memory_enabled": True, "api_key_env": "KB_TEST_OV_KEY"})
        context.write_json(context.config_path(self.root), cfg)
        os.environ["KB_TEST_OV_KEY"] = "test-key-not-a-real-secret"
        self.transport = FakeTransport()
        self.client = ov_memory.MemoryClient({"url": "http://127.0.0.1:1933", "api_key": "k" * 12, "timeout": 5})
        self.client.keep_recent_count = 10
        self.client.request = self.transport  # 打桩：不发真实网络请求
        # 就绪探针是 commit 的前置门（见 NegativeTests 里的两条反例），正例统一放行
        self.client.check_ready = lambda: {"ok": True, "http_status": 200, "payload": {"status": "ready"}}

    def tearDown(self) -> None:
        os.environ.pop("KB_TEST_OV_KEY", None)
        self._tmp.cleanup()


class SettingsTests(MemoryBase):
    def test_memory_is_off_by_default(self) -> None:
        default = context.default_config("user")
        self.assertFalse(default["ov"]["memory_enabled"])
        self.assertEqual(10, default["ov"]["keep_recent_count"])
        self.assertEqual(180, default["ov"]["task_timeout"])

    def test_disabled_is_a_named_gate_not_a_crash(self) -> None:
        cfg = context.load_config(self.root)
        cfg["ov"]["memory_enabled"] = False
        context.write_json(context.config_path(self.root), cfg)
        with self.assertRaises(ov_memory.MemoryError) as ctx:
            ov_memory.client_for(self.root)
        self.assertEqual("memory_disabled", ctx.exception.gate)

    def test_missing_url_fails_as_config_error(self) -> None:
        cfg = context.load_config(self.root)
        cfg["ov"]["url"] = ""
        context.write_json(context.config_path(self.root), cfg)
        with self.assertRaises(ov_remote.OVConfigError):
            ov_memory.client_for(self.root)

    def test_local_server_needs_no_api_key(self) -> None:
        """本机 OpenViking 是 dev 模式、没有密钥；硬要 key 会让本地部署装好即不可用。"""
        cfg = context.load_config(self.root)
        cfg["ov"]["api_key_file"] = ""
        context.write_json(context.config_path(self.root), cfg)
        os.environ.pop("KB_TEST_OV_KEY", None)
        settings = ov_remote.resolve_settings(context.load_config(self.root))
        self.assertEqual("", settings["api_key"])
        client = ov_remote.RemoteClient(settings)
        self.assertNotIn("X-API-Key", client._headers())

    def test_remote_server_still_requires_a_key(self) -> None:
        settings = {"ov": {"url": "https://kb.example.com", "api_key_env": "KB_TEST_NO_SUCH_KEY"}}
        with self.assertRaises(ov_remote.OVConfigError):
            ov_remote.resolve_settings(settings)


class RequestShapeTests(MemoryBase):
    def test_create_session_posts_to_sessions(self) -> None:
        self.client.create_session("s-fixed")
        call = self.transport.calls[0]
        self.assertEqual(("POST", "/api/v1/sessions"), (call["method"], call["path"]))
        self.assertEqual({"session_id": "s-fixed"}, call["body"])

    def test_add_message_posts_role_and_content(self) -> None:
        self.client.add_message("s-1", "user", "你好")
        call = self.transport.calls[0]
        self.assertEqual("/api/v1/sessions/s-1/messages", call["path"])
        self.assertEqual({"role": "user", "content": "你好"}, call["body"])

    def test_batch_respects_the_server_limit_of_100(self) -> None:
        messages = [{"role": "user", "content": f"m{i}"} for i in range(101)]
        result = self.client.add_messages("s-1", messages)
        self.assertEqual(2, result["batches"], result)
        self.assertEqual([100, 1], [len(c["body"]["messages"]) for c in self.transport.calls])

    def test_commit_and_task_polling_paths(self) -> None:
        self.client.commit("s-1", keep_recent_count=3)
        self.client.wait_task("t-1")
        self.assertEqual(
            [("POST", "/api/v1/sessions/s-1/commit"), ("GET", "/api/v1/tasks/t-1")],
            [(c["method"], c["path"]) for c in self.transport.calls],
        )
        self.assertEqual(3, self.transport.calls[0]["body"]["keep_recent_count"])


class FlowTests(MemoryBase):
    def test_begin_append_commit_status(self) -> None:
        started = ov_memory.begin(self.root, client=self.client)
        self.assertEqual("s-test-1", started["session_id"])
        self.assertTrue(Path(started["state"]).is_file())

        added = ov_memory.append(self.root, "user", "会话记忆为什么没被记录", client=self.client)
        self.assertGreater(added["chars"], 0)
        self.assertEqual(1, ov_memory.load_state(self.root)["add_count"])

        committed = ov_memory.commit(self.root, client=self.client)
        self.assertEqual("t-test-1", committed["task_id"])
        self.assertTrue(committed["waited"])
        self.assertTrue(committed["task_ok"])
        evidence = context.load_json(Path(committed["evidence"]), {})
        self.assertEqual("completed", (evidence.get("task") or {}).get("status"))
        self.assertEqual("t-test-1", evidence["task_id"])

        status = ov_memory.status(self.root, client=self.client)
        self.assertEqual(3, status["server_message_count"])
        self.assertEqual(2, status["memories_extracted"]["total"])
        self.assertEqual(1, status["local_commits"])

    def test_commit_without_wait_does_not_poll(self) -> None:
        ov_memory.begin(self.root, client=self.client)
        self.transport.calls.clear()
        result = ov_memory.commit(self.root, client=self.client, wait=False)
        self.assertFalse(result["waited"])
        self.assertEqual(1, len(self.transport.calls))
        self.assertTrue(result["task_id"])

    def test_batch_flow_counts_every_message(self) -> None:
        ov_memory.begin(self.root, client=self.client)
        result = ov_memory.append_many(
            self.root,
            [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}],
            client=self.client,
        )
        self.assertEqual(2, result["added"])
        self.assertEqual(2, ov_memory.load_state(self.root)["add_count"])

    def test_used_records_contexts(self) -> None:
        ov_memory.begin(self.root, client=self.client)
        ov_memory.mark_used(self.root, contexts=["viking://resources/domains/user/index.md"], client=self.client)
        call = self.transport.calls[-1]
        self.assertTrue(call["path"].endswith("/used"))
        self.assertEqual(["viking://resources/domains/user/index.md"], call["body"]["contexts"])


class NegativeTests(MemoryBase):
    def test_append_without_session_is_a_named_gate(self) -> None:
        with self.assertRaises(ov_memory.MemoryError) as ctx:
            ov_memory.append(self.root, "user", "x", client=self.client)
        self.assertEqual("memory_no_session", ctx.exception.gate)

    def test_empty_batch_is_refused(self) -> None:
        with self.assertRaises(ov_memory.MemoryError) as ctx:
            self.client.add_messages("s-1", [])
        self.assertEqual("memory_empty_batch", ctx.exception.gate)

    def test_task_timeout_is_reported_and_evidence_is_still_written(self) -> None:
        """提交已经在服务端发生（task_id 到手），只是没等到终态——留证不能因此消失。"""
        ov_memory.begin(self.root, client=self.client)
        self.client.request = FakeTransport({"/api/v1/tasks/": {"task_id": "t-test-1", "status": "running"}})
        with self.assertRaises(ov_memory.MemoryError) as ctx:
            ov_memory.commit(self.root, client=self.client)
        self.assertEqual("memory_task_timeout", ctx.exception.gate)
        evidence = ctx.exception.extra.get("evidence")
        self.assertTrue(evidence and Path(evidence).is_file(), ctx.exception.extra)
        payload = context.load_json(Path(evidence), {})
        self.assertEqual("t-test-1", payload["task_id"])
        self.assertIn("wait_error", payload)

    def test_server_error_envelope_surfaces_the_code(self) -> None:
        self.client.request = FakeTransport(
            {"/api/v1/sessions": ov_remote.OVRemoteError("SESSION_LIMIT", "too many sessions")}
        )
        with self.assertRaises(ov_remote.OVRemoteError) as ctx:
            self.client.create_session()
        self.assertEqual("SESSION_LIMIT", ctx.exception.code)

    def test_used_requires_something_to_record(self) -> None:
        with self.assertRaises(ov_memory.MemoryError) as ctx:
            self.client.record_used("s-1")
        self.assertEqual("memory_empty_used", ctx.exception.gate)

    def test_completed_task_without_memories_is_flagged_not_celebrated(self) -> None:
        """实测踩到：模型配额不足时服务端仍把任务标成 completed、却抽不出记忆。

        只看任务状态会把"抽取失败"报成"抽取成功"——这里把那条歧义钉住：
        任务完成但零产出零用量时必须给出提醒，不许默认成功。
        """
        summary = ov_memory.extraction_summary(
            {"status": "completed", "result": {"memories_extracted": {}, "token_usage": {"llm": {"total_tokens": 0}}}}
        )
        self.assertTrue(summary["task_ok"])
        self.assertEqual(0, summary["memories_total"])
        self.assertIn("extraction_note", summary)
        self.assertIn("配额", summary["extraction_note"])

    def test_extracted_memories_are_counted_without_a_note(self) -> None:
        summary = ov_memory.extraction_summary(
            {
                "status": "completed",
                "result": {
                    "memories_extracted": {"preferences": 2, "entities": 1},
                    "token_usage": {"llm": {"total_tokens": 1234}},
                },
            }
        )
        self.assertEqual(3, summary["memories_total"])
        self.assertEqual(1234, summary["llm_tokens"])
        self.assertNotIn("extraction_note", summary)

    def test_failed_task_is_not_ok(self) -> None:
        summary = ov_memory.extraction_summary({"status": "failed", "_failed": True, "result": {}})
        self.assertFalse(summary["task_ok"])

    def test_commit_refuses_to_write_when_instance_is_not_ready(self) -> None:
        """就绪门：端点不可用时宁可拒提交，也不要白提交一次并留下"看起来成功"的留证。"""
        ov_memory.begin(self.root, client=self.client)
        self.transport.calls.clear()
        self.client.check_ready = lambda: {
            "ok": False,
            "http_status": 503,
            "reason": "not ready",
            "payload": {"status": "not_ready", "checks": {"embedding": "error"}},
        }
        with self.assertRaises(ov_memory.MemoryError) as ctx:
            ov_memory.commit(self.root, client=self.client)
        self.assertEqual("memory_not_ready", ctx.exception.gate)
        self.assertEqual([], self.transport.calls, "未就绪时不该发出 commit 请求")
        evidence = list((self.root / ".kb" / "runtime" / "memory").glob("commit-*.json"))
        self.assertEqual([], evidence, "未就绪时不该留下提交留证")

    def test_ready_probe_reports_http_status_and_payload(self) -> None:
        client = ov_memory.MemoryClient({"url": "http://127.0.0.1:1933", "api_key": "k" * 12, "timeout": 5})
        with mock.patch.object(
            ov_memory.ov_remote.RemoteClient, "_send", return_value=(b'{"status":"ready"}', 200)
        ):
            result = client.check_ready()
        self.assertTrue(result["ok"])
        self.assertEqual(200, result["http_status"])
        self.assertEqual("ready", result["payload"]["status"])


def load_sessionstart():
    """把 hooks/sessionstart.py 作为模块加载（它依赖 hooks/common.py 与 engine/core）。"""
    spec = importlib.util.spec_from_file_location("kb_sessionstart", ROOT_REPO / "hooks" / "sessionstart.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("kb_sessionstart", module)
    spec.loader.exec_module(module)
    return module


class SessionStartWiringTests(MemoryBase):
    """SessionStart 的自动 begin：启用才动，且任何失败都必须 fail-open。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.hook = load_sessionstart()

    def _set_enabled(self, enabled: bool, url: str = "http://127.0.0.1:1933") -> None:
        cfg = context.load_config(self.root)
        cfg["ov"]["memory_enabled"] = enabled
        cfg["ov"]["url"] = url
        context.write_json(context.config_path(self.root), cfg)

    def test_disabled_means_silence(self) -> None:
        self._set_enabled(False)
        self.assertEqual("", self.hook._memory_note(self.root))

    def test_unreachable_server_does_not_break_session_start(self) -> None:
        """记忆链路连不上时 hook 必须静默跳过——否则会话启动被自己插件的网络问题打断。"""
        self._set_enabled(True, url="http://127.0.0.1:1")
        self.assertEqual("", self.hook._memory_note(self.root))

    def test_enabled_and_bound_session_is_reused(self) -> None:
        self._set_enabled(True)
        ov_memory.save_state(self.root, {"session_id": "s-existing"})
        note = self.hook._memory_note(self.root)
        self.assertIn("s-existing", note)
        self.assertIn("复用", note)
        self.assertIn("memory commit", note, "开场就要提示收工动作，否则没人记得提交")

    def test_enabled_without_session_creates_one(self) -> None:
        self._set_enabled(True)
        with mock.patch.object(ov_memory, "begin", return_value={"session_id": "s-from-hook"}) as begin:
            note = self.hook._memory_note(self.root)
        self.assertTrue(begin.called)
        self.assertIn("s-from-hook", note)


class DisabledPrecedenceTest(unittest.TestCase):
    """KBP-060：关着记忆时，命令层要先说「没启用」，而不是先说「没有会话」。

    现场（2026-10-14 插件测试用例 K-22）：未启用时 `memory status` 回的是
    「先跑 memory begin」，而 begin 又会回「没启用」——门指错了方向，
    用户照着提示跑一遍还是错的。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        context.ensure_app_dir(self.root, mode="live", domain="user")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_status_reports_disabled_first(self) -> None:
        with self.assertRaises(ov_memory.MemoryError) as ctx:
            ov_memory.status(self.root)
        self.assertEqual("memory_disabled", ctx.exception.gate)

    def test_commit_reports_disabled_first(self) -> None:
        with self.assertRaises(ov_memory.MemoryError) as ctx:
            ov_memory.commit(self.root)
        self.assertEqual("memory_disabled", ctx.exception.gate)

    def test_mark_used_reports_disabled_first(self) -> None:
        with self.assertRaises(ov_memory.MemoryError) as ctx:
            ov_memory.mark_used(self.root, contexts=["viking://resources/x.md"])
        self.assertEqual("memory_disabled", ctx.exception.gate)


if __name__ == "__main__":
    unittest.main()
