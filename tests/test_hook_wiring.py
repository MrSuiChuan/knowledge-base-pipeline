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
"""Run the configured hook command for real, through this platform's shell.

`tests/test_pipeline.py` 用 `sys.executable` 直接跑 hook，证明的是决策逻辑；
本文件跑的是 `hooks/*.json` 里**配置的那条命令**，证明的是接线本身
（路径、引号、启动器都对得上）。两者互补：前者平台无关，后者才是用户真正会遇到的东西。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_REPO = Path(__file__).resolve().parent.parent
HOOKS_FILE = ROOT_REPO / "hooks" / "claude-codex-hooks.json"


def pretooluse_command() -> str:
    data = json.loads(HOOKS_FILE.read_text(encoding="utf-8"))
    command = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    return command.replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT_REPO))


def configured_launcher(command: str) -> str:
    stripped = command.strip()
    return stripped.split()[0] if stripped else ""


class HookWiringTests(unittest.TestCase):
    """这些用例故意慢：每次都要真起一个 hook 进程。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        # 没有 .kb/ 的干净目录：setup_guard 的触发条件
        self.workdir = Path(self._tmp.name)
        # hooks/*.json 的提交默认是 Windows 的 `py -3`。在 POSIX 上它是"还没装好"，
        # 不是"接线坏了"——这两种状态必须分开：前者交给 adapt_hooks.py --check 报告，
        # 后者才是本测试要抓的。CI 的 hooks job 会先 adapt 再跑本测试，
        # 所以跨平台接线在那里是真的被验证过的。
        launcher = configured_launcher(pretooluse_command())
        if not shutil.which(launcher):
            self.skipTest(
                f"hooks 配置的启动器 {launcher!r} 在本机不存在，无法真实触发 hook。"
                "这不是仓库的问题：hooks/*.json 默认是 Windows 的 `py -3`，"
                "POSIX 上要先跑 `python3 tools/adapt_hooks.py`（`--check` 可体检）。"
            )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run_hook(self, payload: dict) -> dict:
        command = pretooluse_command()
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_ROOT"] = str(ROOT_REPO)
        proc = subprocess.run(
            command,
            shell=True,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(self.workdir),
            env=env,
            timeout=120,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"hook 命令没能正常跑完（疑似启动器在本机不存在）: {command}\n"
            f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}",
        )
        body = (proc.stdout or "").strip()
        self.assertTrue(body, f"hook 没有输出决策（启动器或导入失败）: stderr={proc.stderr!r}")
        return json.loads(body.splitlines()[-1])

    def _payload(self, tool_name: str, tool_input: dict) -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "cwd": str(self.workdir),
            "tool_name": tool_name,
            "tool_input": tool_input,
        }

    def test_bare_cli_before_setup_is_denied(self) -> None:
        out = self._run_hook(self._payload("Bash", {"command": "kbp.py publish --domain user"}))
        self.assertEqual(out.get("decision"), "block", out)
        self.assertEqual(out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny", out)

    def test_readonly_mention_of_cli_name_is_allowed(self) -> None:
        """实测误伤回归：只读检索/打印一个词不该被拦。"""
        for command in (
            'rg -n "^def verb_" engine/kbp.py',
            'echo "=== OpenViking 远程集成 ==="',
        ):
            out = self._run_hook(self._payload("Bash", {"command": command}))
            self.assertNotEqual(out.get("decision"), "block", f"{command} -> {out}")

    def test_ungated_tool_takes_fast_path(self) -> None:
        out = self._run_hook(self._payload("Read", {"file_path": "README.md"}))
        self.assertEqual(out, {}, out)


if __name__ == "__main__":
    unittest.main()
