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
"""End-to-end: mock demo lifecycle, hook smoke tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_REPO = Path(__file__).resolve().parent.parent
ENGINE = ROOT_REPO / "engine"
sys.path.insert(0, str(ENGINE))

from core import context  # noqa: E402


def run_engine(root: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ENGINE / "kbp.py"), "--root", str(root), *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class DemoLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_demo_full_lifecycle(self) -> None:
        proc = run_engine(self.root, "demo", "--domain", "user")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        manifest = json.loads((self.root / ".kb" / "repo" / ".kb-manifest.json").read_text(encoding="utf-8"))
        versions = [p["version"] for p in manifest["publishes"]]
        self.assertEqual(versions, ["kb-v1", "kb-v2"])
        rule_path = self.root / ".kb" / "repo" / "rules" / "user" / "DQ-USER-PK-UNIQUE.yaml"
        self.assertIn("status: active", rule_path.read_text(encoding="utf-8"))

    def test_publish_without_audit_via_cli_blocked(self) -> None:
        run_engine(self.root, "setup", "--mode", "mock", "--domain", "user")
        proc = run_engine(self.root, "publish", "--domain", "user", "--reason", "没审计")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("kb_publish_guard", proc.stdout)


class HookSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        context.ensure_app_dir(self.root, mode="mock", domain="user")
        self.env = dict(os.environ)
        self.env["CLAUDE_PLUGIN_ROOT"] = str(ROOT_REPO)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _hook(self, name: str, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT_REPO / "hooks" / name)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self.env,
            cwd=str(self.root),
        )

    def test_publish_without_audit_blocked_by_hook(self) -> None:
        proc = self._hook(
            "pretooluse.py",
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": "kbp.py publish --domain user --reason x", "description": ""},
            },
        )
        # 宿主 schema 是 additionalProperties:false：用 exit 0 + JSON 决策表达阻断
        # （exit 2 只在"把原因写 stderr"的旧协议里有效，且多余字段会让宿主忽略整条决策）
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("decision"), "block")
        specific = payload["hookSpecificOutput"]
        self.assertEqual(specific.get("permissionDecision"), "deny")
        self.assertIn("kb_publish_guard", specific.get("permissionDecisionReason", ""))

    def test_plain_command_allowed(self) -> None:
        proc = self._hook(
            "pretooluse.py",
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": "echo hi", "description": ""},
            },
        )
        self.assertEqual(proc.returncode, 0)

    def test_rules_write_blocked_by_hook(self) -> None:
        path = self.root / ".kb" / "repo" / "rules" / "user" / "DQ-X.yaml"
        proc = self._hook(
            "pretooluse.py",
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(self.root),
                "tool_name": "Write",
                "tool_input": {"file_path": str(path), "content": "id: x"},
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("decision"), "block")
        specific = payload["hookSpecificOutput"]
        self.assertIn("rules_direct_write_guard", specific.get("permissionDecisionReason", ""))
        # 只允许 schema 内的键：多写字段会被宿主整条忽略
        self.assertLessEqual(
            set(payload),
            {"continue", "decision", "hookSpecificOutput", "reason", "stopReason", "suppressOutput", "systemMessage"},
        )
        self.assertLessEqual(
            set(specific),
            {"hookEventName", "permissionDecision", "permissionDecisionReason", "additionalContext"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
