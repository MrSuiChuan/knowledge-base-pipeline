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
"""ov_remote 传输器 + publish 远端接线测试（HTTP 全部 mock，不发真实网络请求）。"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT_REPO = Path(__file__).resolve().parent.parent
ENGINE = ROOT_REPO / "engine"
sys.path.insert(0, str(ENGINE))

from core import audit, context, ov_remote, sync  # noqa: E402


class UriHelperTests(unittest.TestCase):
    def test_parent_dirs_skips_scope_root_and_leaf(self) -> None:
        self.assertEqual(
            ov_remote.parent_dirs("viking://resources/domains/user/tables/dwd_user_di.md"),
            ["viking://resources/domains", "viking://resources/domains/user", "viking://resources/domains/user/tables"],
        )

    def test_parent_dirs_scope_root_only(self) -> None:
        self.assertEqual(ov_remote.parent_dirs("viking://resources/README.md"), [])

    def test_parent_dirs_include_scope_root(self) -> None:
        self.assertEqual(
            ov_remote.parent_dirs("viking://projects/kb/README.md", include_scope_root=True),
            ["viking://projects", "viking://projects/kb"],
        )

    def test_invalid_uri_rejected(self) -> None:
        with self.assertRaises(ov_remote.OVRemoteError):
            ov_remote.parent_dirs("https://example.com/x.md")


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _cfg(self, **ov) -> dict:
        base = {
            "ov": {
                "remote_enabled": True,
                "url": "http://127.0.0.1:1933",
                "api_key_env": "OV_API_KEY",
                **ov,
            }
        }
        return base

    def test_missing_url_blocks(self) -> None:
        cfg = self._cfg(url="")
        with mock.patch.dict(os.environ, {"OV_API_KEY": "x" * 20}, clear=False):
            with self.assertRaises(ov_remote.OVConfigError):
                ov_remote.resolve_settings(cfg)

    def test_missing_key_blocks_on_remote_hosts(self) -> None:
        """远端主机缺 key 仍然拦。

        契约在 2026-10-11 变过一次，只放开**本机地址**：本机 OpenViking 是 dev 模式
        （服务端 server/auth.py: "Dev mode: no authentication, always return ROOT"），
        ovcli.conf 里本来就没有密钥；硬要 key 会让本地部署"装好即不可用"。
        本机免 key 的正面用例在 tests/test_memory.py::SettingsTests。
        """
        cfg = self._cfg(url="https://kb.example.com", api_key_env="OV_TEST_KEY_NEVER_SET")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ov_remote.OVConfigError):
                ov_remote.resolve_settings(cfg)

    def test_missing_key_is_allowed_for_local_dev_server(self) -> None:
        cfg = self._cfg(api_key_env="OV_TEST_KEY_NEVER_SET")
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = ov_remote.resolve_settings(cfg)
        self.assertEqual("", settings["api_key"])

    def test_env_key_wins(self) -> None:
        cfg = self._cfg()
        with mock.patch.dict(os.environ, {"OV_API_KEY": "secret-123456"}, clear=False):
            settings = ov_remote.resolve_settings(cfg)
        self.assertEqual(settings["api_key"], "secret-123456")

    def test_api_key_file_supported(self) -> None:
        key_path = self.root / "ov.key"
        key_path.write_text("file-secret-123456\n", encoding="utf-8")
        cfg = self._cfg(api_key_env="OV_API_KEY", api_key_file=str(key_path))
        with mock.patch.dict(os.environ, {"OV_API_KEY": ""}, clear=True):
            settings = ov_remote.resolve_settings(cfg)
        self.assertEqual(settings["api_key"], "file-secret-123456")


class FakeRemote:
    """In-memory OpenViking HTTP 替身。"""

    def __init__(self, fail_uri: str = "") -> None:
        self.store: dict = {}
        self.dirs: set = set()
        self.fail_uri = fail_uri
        self.mkdir_calls: list = []
        self.write_calls: list = []

    def stat(self, uri: str):
        if uri in self.store:
            return {"isDir": False, "name": uri.rsplit("/", 1)[-1]}
        if uri in self.dirs:
            return {"isDir": True, "name": uri.rsplit("/", 1)[-1]}
        return None

    def mkdir(self, uri: str) -> dict:
        self.dirs.add(uri)
        self.mkdir_calls.append(uri)
        return {"uri": uri}

    def write_file(self, uri: str, content: str) -> dict:
        if self.fail_uri and uri == self.fail_uri:
            raise ov_remote.OVRemoteError("NOT_FOUND", f"写入失败: {uri}", uri=uri)
        self.store[uri] = content
        self.write_calls.append(uri)
        return {"uri": uri, "written_bytes": len(content)}

    def read(self, uri: str) -> str:
        return self.store[uri]

    def download_raw(self, uri: str) -> bytes:
        return self.store[uri].encode("utf-8")


class PushFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        cfg = {
            "ov": {
                "remote_enabled": True,
                "url": "http://127.0.0.1:1933",
                "api_key_env": "OV_TEST_KEY_FAKE",
            }
        }
        self.cfg = cfg

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_push_files_creates_parents_writes_verifies(self) -> None:
        fake = FakeRemote()
        files = [
            ("viking://resources/domains/user/tables/a.md", "# a"),
            ("viking://resources/README.md", "# root"),
        ]
        with mock.patch.dict(os.environ, {"OV_TEST_KEY_FAKE": "fake-key-123"}, clear=False):
            with mock.patch.object(ov_remote, "RemoteClient", return_value=fake):
                result = ov_remote.push_files(self.cfg, files)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["pushed"], [u for u, _ in files])
        self.assertIn("viking://resources/domains/user/tables", fake.mkdir_calls)
        self.assertIn("viking://resources/domains/user", fake.mkdir_calls)
        self.assertEqual(set(fake.store), {u for u, _ in files})

    def test_push_files_honest_failure(self) -> None:
        target = "viking://resources/domains/user/tables/broken.md"
        fake = FakeRemote(fail_uri=target)
        files = [(target, "# broken")]
        with mock.patch.dict(os.environ, {"OV_TEST_KEY_FAKE": "fake-key-123"}, clear=False):
            with mock.patch.object(ov_remote, "RemoteClient", return_value=fake):
                result = ov_remote.push_files(self.cfg, files)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "NOT_FOUND")
        self.assertIn(target, result["reason"])


class PublishRemoteTests(unittest.TestCase):
    """publish 与 ov_remote 的接线：成功标 remote，失败不许假成功。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        context.ensure_app_dir(self.root, mode="mock", domain="user")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run_demo_and_arm_remote(self) -> None:
        """跑通 demo（mock 全流程：知识树+审计+审阅），再切 live+远端配置。"""
        proc = subprocess.run(
            [sys.executable, str(ENGINE / "kbp.py"), "--root", str(self.root), "demo", "--domain", "user"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        cfg = context.load_config(self.root)
        cfg["mode"] = "live"
        cfg["ov"] = {
            "remote_enabled": True,
            "url": "http://127.0.0.1:1933",
            "api_key_env": "OV_TEST_KEY_FAKE",
            "api_key_file": "",
        }
        context.write_json(context.config_path(self.root), cfg)

    def test_publish_success_marks_remote(self) -> None:
        self._run_demo_and_arm_remote()
        fake_remote = {
            "ok": True,
            "configured": True,
            "server": "http://127.0.0.1:1933",
            "pushed": ["viking://resources/domains/user/index.md"],
            "verified": 1,
            "failed": [],
        }
        with mock.patch.dict(os.environ, {"OV_TEST_KEY_FAKE": "fake-key-123"}, clear=False):
            with mock.patch.object(sync.ov_remote, "push_files", return_value=fake_remote) as push:
                result = sync.publish(self.root, "user", reason="t")
        self.assertTrue(result["ok"], result)
        push.assert_called_once()
        pushed_files = push.call_args.args[1]
        self.assertFalse(
            any(uri.endswith("README.md") for uri, _ in pushed_files),
            "scope_readme=false 时不得把 repo README 推到共享 scope 根",
        )
        manifest = context.load_json(context.repo_dir(self.root) / ".kb-manifest.json")
        self.assertEqual(manifest["publishes"][-1]["ov_sync"], "remote")
        self.assertEqual(manifest["publishes"][-1]["remote"]["verified"], 1)
        sync_state = context.load_json(context.runtime_dir(self.root) / ".kb-sync-state.json")
        self.assertEqual(sync_state["ov_sync"], "remote")

    def test_publish_remote_failure_blocks_and_no_manifest_entry(self) -> None:
        self._run_demo_and_arm_remote()
        manifest_path = context.repo_dir(self.root) / ".kb-manifest.json"
        before = context.load_json(manifest_path)
        versions_before = [p["version"] for p in before["publishes"]]
        fail_remote = {
            "ok": False,
            "configured": True,
            "server": "http://127.0.0.1:1933",
            "code": "NOT_FOUND",
            "reason": "远端同步失败 viking://resources/README.md: File not found",
            "pushed": [],
            "verified": 0,
            "failed": [{"uri": "viking://resources/README.md", "code": "NOT_FOUND", "message": "File not found"}],
        }
        with mock.patch.dict(os.environ, {"OV_TEST_KEY_FAKE": "fake-key-123"}, clear=False):
            with mock.patch.object(sync.ov_remote, "push_files", return_value=fail_remote):
                result = sync.publish(self.root, "user", reason="t")
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertEqual(result["gate"], "ov_remote_sync")
        after = context.load_json(manifest_path)
        self.assertEqual(
            [p["version"] for p in after["publishes"]],
            versions_before,
            "远端失败时不得新增发布清单条目",
        )


class CheckConnectionTests(unittest.TestCase):
    """ov-check 要能看出"健康"与"就绪"两件事（实测两个坑，见 check_connection 的注释）。"""

    def _config(self) -> dict:
        return {
            "ov": {
                "remote_enabled": True,
                "url": "https://kb.example.com",
                "api_key_env": "OV_TEST_CHECK_KEY",
            }
        }

    def test_flat_health_is_reported_not_swallowed(self) -> None:
        """0.4.11 的 /health 是扁平返回（没有 result 信封），不能被解包成 None。"""
        raw = b'{"status":"ok","healthy":true,"version":"0.4.11","auth_mode":"api_key"}'
        with mock.patch.dict(os.environ, {"OV_TEST_CHECK_KEY": "k" * 20}, clear=False):
            with mock.patch.object(ov_remote.RemoteClient, "_send", side_effect=[(raw, 200), (b'{"status":"ready"}', 200)]):
                result = ov_remote.check_connection(self._config())
        self.assertTrue(result["ok"])
        self.assertEqual("0.4.11", result["health"]["version"])
        self.assertTrue(result["health"]["healthy"])
        self.assertTrue(result["ready_ok"])

    def test_not_ready_is_visible_even_when_health_is_ok(self) -> None:
        """embedding 挂掉时 /ready 给 503、/health 仍 200——只看 health 会漏报。"""
        health = (b'{"status":"ok","healthy":true}', 200)
        not_ready = ov_remote.OVRemoteError("HTTP_503", "not ready", http_status=503)
        with mock.patch.dict(os.environ, {"OV_TEST_CHECK_KEY": "k" * 20}, clear=False):
            with mock.patch.object(ov_remote.RemoteClient, "_send", side_effect=[health, not_ready]):
                result = ov_remote.check_connection(self._config())
        self.assertTrue(result["ok"], "健康检查本身是通的")
        self.assertFalse(result["ready_ok"], "但就绪必须如实报 false")
        self.assertEqual(503, result["ready_http"])

    def test_unreachable_server_reports_the_transport_error(self) -> None:
        failing = ov_remote.OVRemoteError("connection", "无法连接", http_status=0)
        with mock.patch.dict(os.environ, {"OV_TEST_CHECK_KEY": "k" * 20}, clear=False):
            with mock.patch.object(ov_remote.RemoteClient, "_send", side_effect=failing):
                result = ov_remote.check_connection(self._config())
        self.assertFalse(result["ok"])
        self.assertTrue(result["configured"])
        self.assertEqual("connection", result["code"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
