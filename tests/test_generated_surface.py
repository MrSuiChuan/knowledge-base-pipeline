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
"""生成物必须与手写源一致。

`tools/build_codex_surface.py` 从 `commands/*.md` 生成 12 个文件（Codex 清单、共用
hooks、9 个 `kbp-*` 入口技能、AGENTS 模板）。改完 command 忘了重跑生成器，Codex 面
就会悄悄落后于 Claude 面——两个宿主跑出不同的流程，而且没有任何报错。

这个仓库的主张是"机器门控不可绕"，所以构建这一步也不能靠"记得重跑"。测试把生成器
输出截在内存里与仓库文件逐字节比对，**不写盘**（写成"先跑生成器再比对"会自己把漂移
修好，然后永远通过）。
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from typing import Dict

ROOT_REPO = Path(__file__).resolve().parent.parent

# 12 = .codex-plugin/plugin.json + hooks/claude-codex-hooks.json + AGENTS.kb.md + 9 个技能
# 13/10 = 2026-10-11 新增 commands/remember.md → skills/kbp-remember/SKILL.md
EXPECTED_COUNT = 13
EXPECTED_SKILLS = 10


def capture_generator_output() -> Dict[str, str]:
    spec = importlib.util.spec_from_file_location(
        "kbp_build_codex_surface", ROOT_REPO / "tools" / "build_codex_surface.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    captured: Dict[str, str] = {}

    def spy(path: Path, text: str) -> None:
        captured[path.relative_to(module.ROOT).as_posix()] = text

    module.write = spy  # 只截获，不落盘
    module.build_codex_manifest()
    module.build_codex_hooks()
    module.build_command_skills()
    module.build_agents_template()
    return captured


class GeneratedSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generated = capture_generator_output()

    def test_generator_still_covers_every_surface_file(self) -> None:
        """防止"少生成几个文件"也能通过后面的比对。"""
        self.assertEqual(len(self.generated), EXPECTED_COUNT, sorted(self.generated))
        skills = [p for p in self.generated if p.startswith("skills/")]
        self.assertEqual(len(skills), EXPECTED_SKILLS, skills)
        for required in (
            ".codex-plugin/plugin.json",
            "hooks/claude-codex-hooks.json",
            "engine/templates/AGENTS.kb.md",
        ):
            self.assertIn(required, self.generated)

    def test_generated_files_match_the_repo_byte_for_byte(self) -> None:
        drift = []
        for rel, want in sorted(self.generated.items()):
            real = ROOT_REPO / rel
            if not real.is_file():
                drift.append(f"{rel}: 生成器会写这个文件，但仓库里没有")
                continue
            have = real.read_text(encoding="utf-8")
            if have != want:
                drift.append(
                    f"{rel}: 与生成器输出不一致（仓库 {len(have)} 字符 / 生成 {len(want)} 字符）"
                )
        self.assertEqual(
            drift,
            [],
            "生成物已漂移，重跑 `py -3 tools/build_codex_surface.py` 后重新提交：\n  "
            + "\n  ".join(drift),
        )

    def test_codex_manifest_keeps_the_cachebuster_suffix(self) -> None:
        """重跑生成器不能把 tools/reinstall.py 写的 +codex.<token> 抹掉。"""
        current = (ROOT_REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        self.assertIn("+codex.", current)
        self.assertIn("+codex.", self.generated[".codex-plugin/plugin.json"])


if __name__ == "__main__":
    unittest.main()
