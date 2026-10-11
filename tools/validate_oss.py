#!/usr/bin/env python3
"""开源标准自检：Apache 项目该有的东西在不在，且互不矛盾。

跑法（仓库根目录）：``py -3 tools/validate_oss.py``（POSIX 用 python3）。失败时返回非零，
每条错误都写清"缺什么、去哪儿补"。

设计纪律：**只查能机器判定的东西**。像"GOVERNANCE 写得好不好"这种交给人工审计
（见 docs/apache-readiness-audit.md），不在这里假装能判。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 一、开源标准要求的文件（缺一个就是一个洞）
REQUIRED_PATHS = [
    "LICENSE",
    "NOTICE",
    "README.md",
    "README.en.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "GOVERNANCE.md",
    "SECURITY.md",
    "SUPPORT.md",
    ".github/CODEOWNERS",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug.md",
    ".github/ISSUE_TEMPLATE/feature.md",
    ".github/ISSUE_TEMPLATE/config-help.md",
    ".github/ISSUE_TEMPLATE/config.yml",
    "docs/README.md",
    "docs/glossary.md",
    "docs/release-process.md",
    "docs/third-party-dependencies.md",
    "docs/apache-readiness-audit.md",
]

LICENSE_HEADER_MARK = "Apache License, Version 2.0"
HEADER_FOLDERS = (("engine", (".py",)), ("hooks", (".py",)), ("tools", (".py", ".sh")), ("tests", (".py",)))
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".tmp", ".awr", ".kb", "node_modules"}

# 二、不许进仓库的个人痕迹。示例一律用占位符。
PERSONAL_PATTERNS = [
    (re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"']+"), "Windows 本机绝对路径"),
    (re.compile(r"\bsuichuan\b|\bwuzongyun\b"), "维护者用户名"),
]
POSIX_HOME = re.compile(r"/home/([a-z][a-z0-9_-]*)/")
# 占位用户名不算个人路径：测试与文档里的 /home/u/、/home/lab/ 是刻意写的假名字。
# （相邻插件 realtime-data-plugin 的用例里就用这些——一刀切会把好内容也拦下。）
HOME_PLACEHOLDERS = {"u", "lab", "user", "username", "example", "test", "me", "you", "youruser", "someone"}


def is_redacted(segment: str) -> bool:
    """已脱敏的写法不算泄漏：``C:\\Users\\...\\``、``<username>``、``%USERNAME%``。

    相邻插件 realtime-data-plugin 的验证记录里有一段引用宿主报错的原文，写的是
    ``C:\\Users\\...\\realtime-data-plugin\\hooks\\hooks.json``——那是**已经脱敏**的证据，
    不该被当成新泄漏拦下来。
    """
    return "..." in segment or segment.startswith("<") or segment.startswith("%")
# 允许出现的例外：自检脚本自身与审计报告要"描述"这些模式。
PERSONAL_EXEMPT = {
    "tools/validate_oss.py",
    "docs/apache-readiness-audit.md",
    ".awr/intake/work-ledger.yaml",
}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def tracked_files() -> list[Path]:
    out: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file():
            out.append(path)
    return out


def check_required_paths() -> list[str]:
    return [f"缺文件：{name}（开源标准要求，见 docs/apache-readiness-audit.md）" for name in REQUIRED_PATHS if not (ROOT / name).is_file()]


def check_license_text() -> list[str]:
    errors: list[str] = []
    text = read(ROOT / "LICENSE")
    if "Apache License" not in text or "Version 2.0" not in text:
        errors.append("LICENSE 不是 Apache-2.0 全文")
    notice = read(ROOT / "NOTICE")
    for need in ("knowledge-base-plugin", "Copyright", "Apache License, Version 2.0"):
        if need not in notice:
            errors.append(f"NOTICE 缺内容：{need}")
    return errors


def check_manifest_fields() -> list[str]:
    """两份清单的 license/author 必须与 LICENSE/NOTICE 口径一致。"""
    errors: list[str] = []
    notice = read(ROOT / "NOTICE")
    m = re.search(r"Copyright \d{4} (.+)", notice)
    owner = m.group(1).strip() if m else ""
    for rel_path in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"缺清单：{rel_path}")
            continue
        try:
            data = json.loads(read(path))
        except json.JSONDecodeError as err:
            errors.append(f"{rel_path} 不是合法 JSON：{err}")
            continue
        if data.get("license") != "Apache-2.0":
            errors.append(f"{rel_path} 的 license 是 {data.get('license')!r}，应为 'Apache-2.0'（与 LICENSE 一致）")
        author = (data.get("author") or {}).get("name")
        if owner and author != owner:
            errors.append(f"{rel_path} 的 author.name={author!r} 与 NOTICE 的署名 {owner!r} 不一致")
        email = (data.get("author") or {}).get("email")
        if email is not None and not str(email).strip():
            errors.append(f"{rel_path} 的 author.email 是空字符串——要么填真实邮箱，要么删掉该字段")
    return errors


def check_license_headers() -> list[str]:
    """自研源码逐文件带许可头。生成物 skills/ 不查（会被生成器覆盖）。"""
    errors: list[str] = []
    for folder, suffixes in HEADER_FOLDERS:
        base = ROOT / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in suffixes or "__pycache__" in path.parts:
                continue
            if LICENSE_HEADER_MARK not in read(path)[:1500]:
                errors.append(f"{rel(path)} 缺 Apache-2.0 许可头")
    return errors


def check_personal_traces() -> list[str]:
    errors: list[str] = []
    for path in tracked_files():
        name = rel(path)
        if name in PERSONAL_EXEMPT:
            continue
        if path.suffix in (".png", ".jpg", ".ico", ".pdf"):
            continue
        text = read(path)
        hit = POSIX_HOME.search(text)
        if hit and hit.group(1) not in HOME_PLACEHOLDERS:
            errors.append(f"{name} 含 POSIX 本机绝对路径：{hit.group(0)!r}（换成占位符）")
            continue
        for pattern, label in PERSONAL_PATTERNS:
            hit = pattern.search(text)
            if hit:
                if is_redacted(hit.group(0)):
                    continue
                errors.append(f"{name} 含{label}：{hit.group(0)!r}（换成占位符）")
                break
    return errors


CHECKS = [
    ("1 开源标准文件齐全", check_required_paths),
    ("2 LICENSE / NOTICE 文本", check_license_text),
    ("3 清单字段与署名一致", check_manifest_fields),
    ("4 自研源码许可头", check_license_headers),
    ("5 无个人路径与用户名", check_personal_traces),
]


def main() -> int:
    total = 0
    for title, fn in CHECKS:
        errors = fn()
        total += len(errors)
        mark = "OK  " if not errors else "FAIL"
        print(f"[{mark}] {title}")
        for err in errors:
            print(f"        - {err}")
    print(f"\n{'通过' if total == 0 else '未通过'}：{total} 处问题")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
