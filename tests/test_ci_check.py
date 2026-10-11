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
"""本地 CI 预检与 ci.yml 的一致性：两边不能各说各话。"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT_REPO = Path(__file__).resolve().parent.parent


def load_ci_check():
    spec = importlib.util.spec_from_file_location("ci_check", ROOT_REPO / "tools" / "ci_check.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ci_check", module)
    spec.loader.exec_module(module)
    return module


class CiCheckConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ci = load_ci_check()

    def test_scan_patterns_come_from_ci_workflow(self) -> None:
        """扫描模式只有一处事实源：ci.yml。本工具不许自己另抄一份。

        这里**不把禁止词写进用例**（写了就等于自己违反了同一套规矩），
        而是独立解析一遍 ci.yml，与工具读出来的做等值比对。
        """
        patterns = self.ci.scan_patterns()
        workflow = (ROOT_REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        # 逐行解析（不能跨行：`[^"]+` 会把两行之间的内容也吃进去）
        from_workflow = tuple(
            re.findall(r'"([^"\n]+)"', line)[0]
            for line in workflow.splitlines()
            if line.strip().startswith("! rg")
        )
        self.assertEqual(2, len(patterns), patterns)
        self.assertEqual(from_workflow, patterns, "工具读出的模式必须与 ci.yml 完全一致")
        self.assertTrue(all("|" in p for p in patterns), patterns)

    def test_scan_includes_hidden_directories(self) -> None:
        """`--hidden` 是 2026-10-11 补的：之前 .awr 台账漏检（rg 默认跳过隐藏目录）。"""
        workflow = (ROOT_REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        for line in workflow.splitlines():
            if line.strip().startswith("! rg"):
                self.assertIn("--hidden", line, line)
        self.assertIn("--hidden", self.ci.SCAN_FLAGS)
        self.assertIn("!.git/**", self.ci.SCAN_EXCLUDES, "扫隐藏目录必须显式排除 .git")

    def test_scan_argv_matches_ci_flags(self) -> None:
        argv = self.ci.scan_argv("foo|bar")
        self.assertEqual(["rg", "-n", "--hidden", "foo|bar", "."], argv[:5])
        self.assertIn("!.github/**", argv)
        self.assertIn("!.git/**", argv)

    def test_workflow_steps_are_all_covered(self) -> None:
        """ci.yml 里每条 `run:` 都应该能在预检里找到对应动作（防"CI 加了步骤、本地没跟上"）。"""
        workflow = (ROOT_REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        # 两种写法都要认：`- run: <cmd>`（test job）与 `run: <cmd>`（hooks job 用 name+run 形式）
        runs = [m.group(1) for line in workflow.splitlines() if (m := re.match(r"-?\s*run:\s*(.*)", line.strip()))]
        expected_fragments = {
            "unittest discover -s tests": False,
            "compileall -q engine hooks tests tools": False,
            "tools/validate_oss.py": False,
            "tools/adapt_hooks.py": False,
            "tests.test_hook_wiring": False,
            "tests.test_engine.CliInvocationTests": False,
        }
        for key in list(expected_fragments):
            expected_fragments[key] = any(key in run for run in runs)
        self.assertTrue(all(expected_fragments.values()), f"ci.yml 里的步骤与预期不一致：{runs}")

    def test_fast_mode_skips_the_suite(self) -> None:
        """--fast 只跳过单测，不跳过扫描（扫描才是 2026-10-11 那次 CI 红的地方）。"""
        source = (ROOT_REPO / "tools" / "ci_check.py").read_text(encoding="utf-8")
        self.assertIn("if not args.fast:", source)
        self.assertIn("4.{index} 脱敏扫描", source)


if __name__ == "__main__":
    unittest.main()
