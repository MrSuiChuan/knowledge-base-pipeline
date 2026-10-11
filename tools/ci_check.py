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
"""本地 CI 预检：把 `.github/workflows/ci.yml` 的每一步在本机跑一遍。

**为什么要有这个**：本仓库吃过大亏——`pytest` 全绿，CI 却红在脱敏扫描上
（2026-10-11，KBP-054：脱敏工具把内部代号写进了源码）。`pytest` 跑的是一部分检查，
CI 跑的是另一套（`unittest discover`、`compileall`、`validate_oss`、两条脱敏扫描、hooks job）。
提交前跑这个，等于把 CI 提前搬到本机。

用法（仓库根目录）::

    py -3 tools/ci_check.py            # 当前解释器跑全部步骤
    py -3 tools/ci_check.py --py-floor # 额外用 Python 3.9（README 承诺的下限）跑单测
    py -3 tools/ci_check.py --fast     # 跳过单测（只查扫描/编译/自检/接线）

与 ci.yml 的一致性由 `tests/test_ci_check.py` 核对：扫描模式直接从 ci.yml 里读，改一处另一处会红。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# CI 的脱敏扫描用 `rg`。标志与排除项必须和 ci.yml 一致——这里的口径由 tests/test_ci_check.py 核对。
SCAN_FLAGS = ("-n", "--hidden")
SCAN_EXCLUDES = ("!.github/**", "!.git/**")


def scan_patterns() -> Tuple[str, ...]:
    """从 ci.yml 里读出扫描模式：**这是唯一事实源**，本文件不另抄一份。"""
    if not CI_WORKFLOW.is_file():
        return ()
    patterns: List[str] = []
    for line in CI_WORKFLOW.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("! rg"):
            match = re.search(r'"([^"]+)"', line)
            if match:
                patterns.append(match.group(1))
    return tuple(patterns)


def scan_argv(pattern: str) -> List[str]:
    argv = ["rg", *SCAN_FLAGS, pattern, "."]
    for item in SCAN_EXCLUDES:
        argv += ["-g", item]
    return argv


def _run(label: str, argv: Sequence[str]) -> Tuple[str, bool, str]:
    proc = subprocess.run(list(argv), cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = proc.returncode == 0
    detail = ""
    if not ok:
        output = (proc.stdout or proc.stderr or "").strip()
        detail = output[-400:] if output else f"rc={proc.returncode}"
    return label, ok, detail


def _scan(label: str, pattern: str) -> Tuple[str, bool, str]:
    """脱敏扫描：rg 找到命中 = 失败（与 CI 的 `! rg … || exit 1` 等价）。"""
    if not shutil.which("rg"):
        return label, True, "（本机没有 rg，跳过——CI 上有）"
    proc = subprocess.run(scan_argv(pattern), cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode == 1:
        return label, True, ""
    if proc.returncode == 0:
        hits = [line for line in proc.stdout.splitlines() if line.strip()][:3]
        return label, False, "命中：" + "；".join(hits)
    return label, False, (proc.stderr or "").strip()[:200]


def floor_python() -> List[str] | None:
    """找本机的 Python 3.9（README 承诺的下限）；找不到就返回 None。

    顺序：`py -3.9` → `python3.9` → uv 装的 cpython-3.9（本机就是这一种，
    `py -3.9` 反而找不到——所以要在候选里带上它，否则 --py-floor 会名存实亡）。
    """
    candidates: List[List[str]] = [["py", "-3.9"], ["python3.9"]]
    uv_root = Path(os.environ.get("APPDATA", "")) / "uv" / "python"
    if uv_root.is_dir():
        candidates += [[str(path)] for path in sorted(uv_root.glob("cpython-3.9*/python.exe"))]
    for parts in candidates:
        found = shutil.which(parts[0]) or (parts[0] if Path(parts[0]).is_file() else None)
        if not found:
            continue
        try:
            probe = subprocess.run([found, *parts[1:], "-c", "import sys"], capture_output=True)
        except OSError:
            continue
        if probe.returncode == 0:
            return [found, *parts[1:]]
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按 ci.yml 的顺序在本机跑一遍 CI")
    parser.add_argument("--fast", action="store_true", help="跳过单测")
    parser.add_argument("--py-floor", dest="py_floor", action="store_true", help="额外用最低支持版本跑单测")
    args = parser.parse_args(list(argv) if argv is not None else None)

    results: List[Tuple[str, bool, str]] = []
    py = sys.executable

    if not args.fast:
        results.append(_run("1 单测（unittest discover）", [py, "-m", "unittest", "discover", "-s", "tests"]))
    results.append(_run("2 编译（compileall）", [py, "-m", "compileall", "-q", "engine", "hooks", "tests", "tools"]))
    results.append(_run("3 开源标准（validate_oss）", [py, "tools/validate_oss.py"]))

    patterns = scan_patterns()
    if not patterns:
        results.append(("4 脱敏扫描", False, f"读不到 {CI_WORKFLOW}"))
    for index, pattern in enumerate(patterns, start=1):
        results.append(_scan(f"4.{index} 脱敏扫描", pattern))

    results.append(_run("5 hook 适配", [py, "tools/adapt_hooks.py"]))
    results.append(_run("6 hook 启动器检查", [py, "tools/adapt_hooks.py", "--check"]))
    results.append(_run("7 hook 真调用", [py, "-m", "unittest", "tests.test_hook_wiring"]))
    results.append(_run("8 门控不回归", [py, "-m", "unittest", "tests.test_engine.CliInvocationTests"]))

    if args.py_floor and not args.fast:
        floor = floor_python()
        if floor:
            results.append(_run("9 单测（最低支持版本）", [*floor, "-m", "unittest", "discover", "-s", "tests"]))
        else:
            results.append(("9 单测（最低支持版本）", True, "（本机没有 3.9，跳过）"))

    print()
    failed = 0
    for label, ok, detail in results:
        mark = "OK  " if ok else "FAIL"
        print(f"[{mark}] {label}" + (f"  {detail}" if detail else ""))
        failed += 0 if ok else 1
    print(f"\n{'全部通过' if failed == 0 else f'{failed} 步失败'}（共 {len(results)} 步）")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
