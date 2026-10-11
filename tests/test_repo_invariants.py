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
"""仓库级不变量：没人守的元数据，迟早和事实分家。

三条都是"读文件、比对"，不起子进程、不写盘，跑完不到一秒：

  * 版本号：Claude 清单是唯一来源，Codex 清单的基础版本与 CHANGELOG 的最新已发布
    小节都必须由它派生；
  * Python 下限：README 承诺的版本必须是 CI 真跑过的，且全部源码能用那个版本的语法解析；
  * 引擎完整性清单：`engine/.engine-manifest.json` 必须与 engine/ 当前内容一致。

注意都**只读不写**：写成"跑生成器再比对"会自己把漂移修好，然后永远通过。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_REPO / "engine"))

from core import context as engine_context  # noqa: E402

CLAUDE_MANIFEST = ROOT_REPO / ".claude-plugin" / "plugin.json"
CODEX_MANIFEST = ROOT_REPO / ".codex-plugin" / "plugin.json"
CHANGELOG = ROOT_REPO / "CHANGELOG.md"
ENGINE_MANIFEST = ROOT_REPO / "engine" / ".engine-manifest.json"
CI_WORKFLOW = ROOT_REPO / ".github" / "workflows" / "ci.yml"
SOURCE_DIRS = ("engine", "hooks", "tools", "tests")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest_version(path: Path) -> str:
    return str(json.loads(path.read_text(encoding="utf-8")).get("version") or "").strip()


def changelog_released_version() -> str:
    """CHANGELOG 里最新的**已发布**版本，跳过 `[Unreleased]`。"""
    for line in CHANGELOG.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^## \[([^\]]+)\]", line)
        if not match:
            continue
        tag = match.group(1).strip()
        if tag.lower() == "unreleased":
            continue
        return tag
    raise AssertionError("CHANGELOG 里找不到已发布版本小节")


def readme_python_floor() -> tuple:
    """README 里承诺的 Python 下限，形如 ``Python 3.9+``。"""
    text = (ROOT_REPO / "README.md").read_text(encoding="utf-8")
    match = re.search(r"Python (\d+)\.(\d+)\+", text)
    if not match:
        raise AssertionError("README.md 里找不到 'Python X.Y+' 形式的下限声明")
    return int(match.group(1)), int(match.group(2))


def ci_python_versions() -> set:
    """ci.yml 里出现过的所有 python-version——标量和矩阵写法都要认。"""
    tested = set()
    for line in CI_WORKFLOW.read_text(encoding="utf-8").splitlines():
        if "python-version:" in line:
            tested.update(re.findall(r"(\d+\.\d+)", line))
    return tested


def source_files() -> list:
    return [
        path
        for sub in SOURCE_DIRS
        for path in sorted((ROOT_REPO / sub).rglob("*.py"))
        if "__pycache__" not in path.parts
    ]


class VersionConsistencyTests(unittest.TestCase):
    def test_base_version_agrees_across_manifests_and_changelog(self) -> None:
        claude = manifest_version(CLAUDE_MANIFEST)
        codex_base = manifest_version(CODEX_MANIFEST).split("+", 1)[0]
        changelog = changelog_released_version()
        self.assertEqual(
            {claude, codex_base, changelog},
            {claude},
            "版本号不一致："
            f".claude-plugin={claude} / .codex-plugin 基础版本={codex_base} / "
            f"CHANGELOG 最新已发布={changelog}。"
            "基础版本以 .claude-plugin/plugin.json 为准，改完请重跑 "
            "tools/build_codex_surface.py。",
        )

    def test_codex_suffix_is_the_codex_cachebuster(self) -> None:
        codex = manifest_version(CODEX_MANIFEST)
        if "+" in codex:
            suffix = codex.split("+", 1)[1]
            self.assertTrue(
                suffix.startswith("codex."),
                f"未知版本后缀：{suffix}（用 tools/reinstall.py 生成）",
            )

    def test_author_name_agrees_across_license_and_manifests(self) -> None:
        """署名与许可口径必须一致，而且不留空 email。

        口径在 2026-10-07 从 MIT 换成 Apache-2.0：Apache-2.0 的官方全文里没有项目署名，
        署名与版权年统一以 NOTICE 为准（这也是 ASF 项目的通行做法）。
        email 那条仍然保留：SECURITY.md 曾经让人"联系 marketplace 元数据里的邮箱"，
        而作者的 email 字段是空字符串——文档指向一个不存在的东西，比没有指引更糟。
        """
        notice = (ROOT_REPO / "NOTICE").read_text(encoding="utf-8")
        match = re.search(r"Copyright (\d{4}) (.+)", notice)
        self.assertIsNotNone(match, "NOTICE 里找不到 Copyright 行")
        owner = match.group(2).strip()
        for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
            data = json.loads((ROOT_REPO / rel).read_text(encoding="utf-8"))
            author = data.get("author") or {}
            self.assertEqual(author.get("name"), owner, f"{rel} 的署名与 NOTICE 不一致")
            self.assertEqual(
                data.get("license"), "Apache-2.0",
                f"{rel} 的 license 字段必须与 LICENSE 一致（Apache-2.0）",
            )
            email = author.get("email")
            if email is not None:
                self.assertTrue(
                    str(email).strip(),
                    f"{rel} 的 author.email 是空字符串——SECURITY.md 之类的文档会指向一个"
                    "不存在的东西。要么填真实邮箱，要么删掉这个字段。",
                )


class PythonFloorTests(unittest.TestCase):
    def test_readme_floor_is_a_version_ci_actually_runs(self) -> None:
        floor = "%d.%d" % readme_python_floor()
        tested = ci_python_versions()
        self.assertIn(
            floor,
            tested,
            f"README 承诺 Python {floor}+，但 CI 只跑 {sorted(tested)}。"
            "要么在 .github/workflows/ci.yml 的矩阵里加上这个版本，要么改 README 的声明——"
            "不要留一个没被验证过的下限。",
        )

    def test_sources_parse_under_the_declared_floor(self) -> None:
        floor = readme_python_floor()
        failures = []
        for path in source_files():
            try:
                # 用 minor 整数形式（3.8 起的原始 API）。元组形式在旧版本上的
                # 支持面更窄——这个测试自己要在 3.9 上跑，不能拿它当赌注。
                ast.parse(
                    path.read_text(encoding="utf-8"),
                    filename=str(path),
                    feature_version=floor[1],
                )
            except SyntaxError as err:
                failures.append(f"{path.relative_to(ROOT_REPO).as_posix()}:{err.lineno} {err.msg}")
        self.assertEqual(
            failures,
            [],
            f"以下文件用了 Python {floor[0]}.{floor[1]} 解析不了的语法：\n  " + "\n  ".join(failures),
        )


class EngineManifestTests(unittest.TestCase):
    def test_manifest_matches_current_engine_files(self) -> None:
        tool = load_module(
            "kbp_generate_engine_manifest", ROOT_REPO / "tools" / "generate_engine_manifest.py"
        )
        expected = tool.build_manifest()
        recorded = json.loads(ENGINE_MANIFEST.read_text(encoding="utf-8")).get("files") or {}

        only_recorded = sorted(set(recorded) - set(expected))
        only_present = sorted(set(expected) - set(recorded))
        changed = sorted(k for k in set(recorded) & set(expected) if recorded[k] != expected[k])

        problems = []
        if only_recorded:
            problems.append(f"清单里有、engine/ 里没有: {only_recorded}")
        if only_present:
            problems.append(f"engine/ 里有、清单里没有: {only_present}")
        if changed:
            problems.append(f"内容变了但清单没更新: {changed}")
        self.assertEqual(
            problems,
            [],
            "engine/.engine-manifest.json 已过期，"
            "跑 `py -3 tools/generate_engine_manifest.py` 后重新提交：\n  " + "\n  ".join(problems),
        )

    def test_hash_is_line_ending_agnostic(self) -> None:
        """清单与知识树审计都必须对行尾风格免疫。

        实测过这一类 bug：本机 `core.autocrlf=true` 时工作副本是 CRLF，新克隆按
        `.gitattributes` 得到 LF，同一份内容字节不同 —— 引擎自检会全线失败，
        知识树审计会把"没改动"判成"内容哈希不一致"从而拦住发布。
        """
        text = "a = 1\nb = 2\nc = 3\n"
        with tempfile.TemporaryDirectory() as tmp:
            lf = Path(tmp) / "lf.md"
            crlf = Path(tmp) / "crlf.md"
            lf.write_bytes(text.encode("utf-8"))
            crlf.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
            self.assertNotEqual(lf.read_bytes(), crlf.read_bytes())
            self.assertEqual(engine_context.sha256_file(lf), engine_context.sha256_file(crlf))

    def test_manifest_tool_and_selfcheck_share_one_hash_rule(self) -> None:
        """生成器与自检必须用同一个哈希函数，否则跨平台必然对不上。"""
        tool = load_module(
            "kbp_generate_engine_manifest2", ROOT_REPO / "tools" / "generate_engine_manifest.py"
        )
        expected = tool.build_manifest()
        sample = ROOT_REPO / "engine" / "core" / "context.py"
        self.assertEqual(expected["core/context.py"], engine_context.sha256_file(sample))


class ToolOutputEncodingTests(unittest.TestCase):
    """工具脚本在非 UTF-8 stdout 下不能崩。

    CI 的 windows 运行器把 stdout 重定向成 cp1252，`adapt_hooks.py --check` 里的中文
    进度行直接 UnicodeEncodeError，整个 job 打红。交互式控制台走 PEP 528 的宽字符 API
    不受影响，所以这个坑**只在 CI / 管道 / 重定向时出现**——必须在测试里显式造出来，
    否则本机永远复现不了。
    """

    def test_adapt_hooks_survives_non_utf8_stdout(self) -> None:
        env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
        proc = subprocess.run(
            [sys.executable, str(ROOT_REPO / "tools" / "adapt_hooks.py"), "--check"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT_REPO),
            env=env,
            timeout=180,
        )
        # --check 在启动器不可用的机器上返回非零是预期的；崩掉才是问题。
        self.assertNotIn("Traceback", proc.stderr, proc.stderr)
        self.assertNotIn("UnicodeEncodeError", proc.stderr, proc.stderr)

    def test_engine_help_survives_non_utf8_stdout(self) -> None:
        """引擎的 HELP 是中文；windows 上把输出重定向就会撞 cp1252（实测崩过）。"""
        env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
        proc = subprocess.run(
            [sys.executable, str(ROOT_REPO / "engine" / "kbp.py"), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT_REPO),
            env=env,
            timeout=180,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("UnicodeEncodeError", proc.stderr, proc.stderr)


if __name__ == "__main__":
    unittest.main()
