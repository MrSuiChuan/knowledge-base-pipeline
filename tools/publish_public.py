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
"""公开镜像同步：把当前提交做成**脱敏快照**，推到公开仓库。

私有仓库 `knowledge-base-plugin` → 公开仓库 `knowledge-base-pipeline`。
两边内容一致，差别只有**脱敏替换**（内网地址、主机名、账号名、密钥文件路径、本机工作区路径）。

用法（仓库根目录）::

    py -3 tools/publish_public.py --check     # 只读：算脱敏结果，报告替换统计与残留
    py -3 tools/publish_public.py --apply     # 生成快照 → 提交 → 推送到公开仓库

设计纪律：

* 快照只取 ``git ls-files`` 的内容（跟踪文件），不把本机运行时产物带出去；
* 替换是**字面量、有序**的（长的在前），不做正则猜测——猜错会连好内容一起改；
* ``--check`` 在推送前做**残留检查**：硬标识（IP/主机名/账号/密钥路径/工作区）一个都不许留；
* 唯一豁免：``.github/workflows/ci.yml`` 里的脱敏检测模式本身（它列的是"禁止出现的词"，
  把这个列表本身也替换掉，检测就形同虚设）；
* 但那行检测表**不能反过来命中镜像自己的文件**：踩过一次（KBP-056）——表里写着内部代号，
  被替换成 ``<account>`` 后，公开 CI 转头去扫文档里的占位符，公开仓库必红。发布前用
  ``detector_selfhits()`` 拦掉。
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REMOTE = "ssh://git@ssh.github.com:443/MrSuiChuan/knowledge-base-pipeline.git"
DEFAULT_MIRROR = ROOT / ".tmp" / "public-mirror"

# 待脱敏的源串**运行时拼装**：这些字面量不能被自己的规则替换掉，
# 否则公开镜像里的规则表会退化成恒等映射（源串变成占位符），工具与用例一起失效。
_SRC_IP = "47.120." + "37.220"
_SRC_HOST = "skillhh" + "-prod"
_SRC_PEM = "~/Downloads/skillhh" + ".pem"
_SRC_PEM_NAME = "skillhh" + ".pem"
_SRC_KEYPATH = "~/.openviking/api" + ".key"
_SRC_TABLE_CELL = "data-dev / kb" + "-admin"
_SRC_USER = "kb" + "-admin"
_SRC_WORKSPACE = "openviking" + "_workspace"

# 内置规则：只放**形状类**标识（地址、主机名、路径、通用用户名）。
# 内部代号、租户名、业务专有名**不进仓库**——它们放在本地词表里（见下）。
# 有序替换表：**长串在前**，否则短的先命中会把长的切碎。
BUILTIN_RULES: Tuple[Tuple[str, str], ...] = (
    (f"http://{_SRC_IP}:1933", "http://<openviking-host>:1933"),
    (f"{_SRC_IP}:1933", "<openviking-host>:1933"),
    (_SRC_IP, "<openviking-host>"),
    (_SRC_HOST, "<host>"),
    (_SRC_PEM, "<ssh-key-file>"),
    (_SRC_KEYPATH, "<key-file>"),
    (_SRC_TABLE_CELL, "<account> / <user>"),
    (_SRC_USER, "<user>"),
    (_SRC_WORKSPACE, "<workspace>"),
)

# 本地词表（**不入库**，见 .gitignore）：内部代号/租户名这类"不能写进仓库"的替换规则。
# 仓库里只有示例文件 tools/public_mirror_terms.example.txt；本机那份由使用者自己维护。
DEFAULT_TERMS_FILE = ROOT / "tools" / "public_mirror_terms.txt"

# 规则表在运行时组装：外部词表在前（更具体），内置在后。
REPLACEMENTS: Tuple[Tuple[str, str], ...] = BUILTIN_RULES

# 硬标识：脱敏后一个都不许残留（出现即视为发布失败）
HARD_PATTERNS: Tuple[str, ...] = (
    _SRC_IP,
    _SRC_HOST,
    _SRC_USER,
    _SRC_PEM_NAME,
    _SRC_WORKSPACE,
)

# 允许残留的文件（脱敏检测模式本身列的就是这些词，替换掉等于废掉检测）
RESIDUAL_ALLOWLIST = (".github/workflows/ci.yml",)

# 检测表的那行 `rg -n --hidden -i "<模式>"`：把模式抠出来，用来验它不会自命中。
_RG_PATTERN = re.compile(r'rg -n(?: -{1,2}[a-zA-Z-]+)*\s+"([^"]+)"')


def sanitize(text: str) -> Tuple[str, Dict[str, int]]:
    """按替换表脱敏，返回（结果, 每条规则命中次数）。"""
    counts: Dict[str, int] = {}
    for src, dst in REPLACEMENTS:
        if src in text:
            counts[f"{src} -> {dst}"] = text.count(src)
            text = text.replace(src, dst)
    return text, counts


def load_terms(path: Path | None = None) -> Tuple[Tuple[Tuple[str, str], ...], List[str]]:
    """加载外部脱敏词表，返回（规则, 说明）。

    格式：每行 ``源串 => 替换``；``#`` 开头与空行忽略。文件默认不在仓库里
    （内部代号不该进 git），仓库只提供 ``tools/public_mirror_terms.example.txt``。
    """
    target = path or DEFAULT_TERMS_FILE
    if not Path(target).is_file():
        return (), [f"未找到外部词表 {target}（只有内置形状规则生效）"]
    rules: List[Tuple[str, str]] = []
    notes: List[str] = []
    for lineno, line in enumerate(Path(target).read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if "=>" not in text:
            notes.append(f"{target}:{lineno} 缺 `=>`，已跳过")
            continue
        src, dst = text.split("=>", 1)
        rules.append((src.strip(), dst.strip()))
    notes.append(f"外部词表 {target}：{len(rules)} 条规则")
    return tuple(rules), notes


def set_rules(extra: Tuple[Tuple[str, str], ...]) -> None:
    """把外部规则放在内置规则之前（外部更具体）。"""
    global REPLACEMENTS
    REPLACEMENTS = tuple(extra) + BUILTIN_RULES


def residuals(text: str, rel: str) -> List[str]:
    """脱敏后仍残留的硬标识（按文件豁免）。"""
    if any(rel.endswith(allowed) for allowed in RESIDUAL_ALLOWLIST):
        return []
    return [pattern for pattern in HARD_PATTERNS if pattern in text]


def detector_selfhits(files: Dict[str, str]) -> List[str]:
    """公开镜像里那行"禁止出现的词"表，不能命中镜像自己的文件。

    ``files`` 传**脱敏后**的内容（即镜像里的样子）。CI 只排除 ``.github/**``，
    这里照做（并更严：只看跟踪文件，不会漏）。踩过的坑见模块 docstring。
    """
    hits: List[str] = []
    for rel, text in files.items():
        if not rel.endswith(".github/workflows/ci.yml"):
            continue
        for pattern in _RG_PATTERN.findall(text):
            try:
                rx = re.compile(pattern, re.IGNORECASE)
            except re.error:
                continue
            for other, body in files.items():
                if other.startswith(".github/"):
                    continue
                if rx.search(body):
                    hits.append(f"{other} 命中检测表模式 {pattern}")
    return hits


def tracked_files() -> List[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"], cwd=str(ROOT), capture_output=True, check=True
    )
    return [name for name in proc.stdout.decode("utf-8").split("\0") if name]


def head_sha() -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check(terms: Path | None = None) -> int:
    extra, notes = load_terms(terms)
    set_rules(extra)
    for note in notes:
        print(note)
    files = tracked_files()
    total: Dict[str, int] = {}
    changed: List[str] = []
    problems: List[str] = []
    cleaned_files: Dict[str, str] = {}
    for rel in files:
        path = ROOT / rel
        try:
            text = read_text(path)
        except (UnicodeDecodeError, OSError):
            continue
        cleaned, counts = sanitize(text)
        cleaned_files[rel] = cleaned
        if counts:
            changed.append(rel)
            for rule, n in counts.items():
                total[rule] = total.get(rule, 0) + n
        left = residuals(cleaned, rel)
        if left:
            problems.append(f"{rel} 脱敏后仍含：{', '.join(left)}")
    for hit in detector_selfhits(cleaned_files):
        problems.append(f"公开镜像检测表自命中：{hit}")

    print(f"跟踪文件 {len(files)} 个；需要脱敏 {len(changed)} 个")
    for rule, n in sorted(total.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3}  {rule}")
    if changed:
        print("涉及文件：" + ", ".join(changed))
    if problems:
        print("\n[FAIL] 有硬标识残留：")
        for item in problems:
            print("  -", item)
        return 1
    print("\n[OK] 脱敏后无硬标识残留")
    return 0


def run_git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check)


def ensure_mirror(mirror: Path, remote: str) -> None:
    if not (mirror / ".git").is_dir():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        print(f"克隆公开仓库 → {mirror}")
        subprocess.run(["git", "clone", "--quiet", remote, str(mirror)], check=True)
        return
    print(f"更新镜像仓库 {mirror}")
    run_git("fetch", "--quiet", "origin", cwd=mirror)
    branch = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=mirror).stdout.strip() or "main"
    run_git("checkout", "-q", branch, cwd=mirror, check=False)
    run_git("merge", "--ff-only", f"origin/{branch}", cwd=mirror, check=False)


def copy_snapshot(dest: Path) -> Dict[str, int]:
    """把脱敏后的跟踪文件写进镜像（先清掉旧跟踪文件，保证是"快照"而不是"叠加"）。"""
    run_git("rm", "-r", "-q", "--ignore-unmatch", ".", cwd=dest, check=False)
    total: Dict[str, int] = {}
    for rel in tracked_files():
        src = ROOT / rel
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = read_text(src)
        except (UnicodeDecodeError, OSError):
            shutil.copy2(src, target)  # 二进制/非 UTF-8：原样复制
            continue
        cleaned, counts = sanitize(text)
        target.write_text(cleaned, encoding="utf-8", newline="")
        for rule, n in counts.items():
            total[rule] = total.get(rule, 0) + n
    return total


def regenerate_derived(dest: Path) -> List[str]:
    """在镜像里重算由内容派生的产物。

    脱敏会改文件内容，凡是"内容哈希"或"由源生成"的东西都得在镜像里重算一遍，
    否则镜像自相矛盾：实测踩到过——`engine/core/ov_remote.py` 的一句注释被脱敏，
    `engine/.engine-manifest.json` 里的 sha256 就与它对不上了，公开仓库的
    `EngineManifestTests` 直接红。
    """
    done: List[str] = []
    for name in ("generate_engine_manifest.py", "build_codex_surface.py"):
        script = dest / "tools" / name
        if not script.is_file():
            continue
        proc = subprocess.run(
            [sys.executable, str(script)], cwd=str(dest), capture_output=True, text=True
        )
        done.append(f"{name}({'ok' if proc.returncode == 0 else 'FAIL'})")
    return done


def apply(remote: str, mirror: Path, push: bool, terms: Path | None = None) -> int:
    if check(terms) != 0:
        print("\n[中止] --check 未通过，不推送。")
        return 1
    ensure_mirror(mirror, remote)
    sha = head_sha()
    counts = copy_snapshot(mirror)
    derived = regenerate_derived(mirror)
    if derived:
        print("重算派生产物：" + "、".join(derived))
    run_git("add", "-A", cwd=mirror)
    status = run_git("status", "--porcelain", cwd=mirror).stdout.strip()
    if not status:
        print("\n[OK] 公开镜像已是最新，无需提交")
        return 0
    rules = "；".join(f"{rule}×{n}" for rule, n in sorted(counts.items(), key=lambda kv: -kv[1])) or "无替换"
    message = f"sync: 公开镜像来自私有仓库 {sha[:8]}（已脱敏）\n\n{_rule_note(rules)}"
    run_git("commit", "-s", "-q", "-m", message, cwd=mirror)
    print(f"\n已提交：{message.splitlines()[0]}")
    print("变更条目数：" + str(len(status.splitlines())))
    if push:
        out = run_git("push", "origin", "HEAD:main", cwd=mirror, check=False)
        if out.returncode != 0:
            print("[FAIL] 推送失败：", (out.stderr or out.stdout).strip()[:400])
            return 1
        print("[OK] 已推送到公开仓库")
    else:
        print("（--no-push：只提交不推送）")
    return 0


def _rule_note(rules: str) -> str:
    return f"本次脱敏替换：{rules}\n\n生成方式：py -3 tools/publish_public.py --apply（脚本随仓库一起公开）"


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把当前提交脱敏后同步到公开仓库")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="只读检查：替换统计 + 残留检查")
    group.add_argument("--apply", action="store_true", help="生成脱敏快照并推送到公开仓库")
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument("--mirror", default=str(DEFAULT_MIRROR))
    parser.add_argument("--terms", default=None, help="外部脱敏词表（每行 `源串 => 替换`；默认 tools/public_mirror_terms.txt，可不配置）")
    parser.add_argument("--no-push", action="store_true", help="只生成提交，不推送")
    args = parser.parse_args(list(argv) if argv is not None else None)

    terms = Path(args.terms) if args.terms else None
    if args.check:
        return check(terms)
    return apply(args.remote, Path(args.mirror), push=not args.no_push, terms=terms)


if __name__ == "__main__":
    sys.exit(main())
