#!/usr/bin/env python3
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
"""Generate the Codex-facing surface of knowledge-base-plugin from the Claude Code sources.

双宿主结构（与 data-development-plugin 同一套做法）：

    .claude-plugin/plugin.json      Claude Code 清单（手写）
    .codex-plugin/plugin.json       Codex 清单（本脚本生成）
    commands/*.md                   Claude Code 斜杠命令 `/kb-xxx`（手写，唯一事实源）
    skills/*/SKILL.md               两宿主共用的方法论技能（手写）
    skills/kbp-*/SKILL.md           Codex 入口技能（本脚本生成；用 kbp- 前缀避免与
                                    已有的 kb-publish / kb-audit 方法论技能撞名）
    hooks/hooks.json                Claude Code hook 配置
    hooks/claude-codex-hooks.json   两宿主共用 hook 配置（本脚本生成）

    py -3 tools/build_codex_surface.py        # Windows
    python3 tools/build_codex_surface.py      # macOS/Linux
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMANDS = ROOT / "commands"
SKILLS = ROOT / "skills"
HOOKS = ROOT / "hooks"
TEMPLATES = ROOT / "engine" / "templates"

PLUGIN_NAME = "knowledge-base-plugin"
CLAUDE_MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
SKILL_PREFIX = "kbp-"


def base_version() -> str:
    """基础版本的唯一来源：手写的 Claude 清单，其余位置全部由它派生。

    原先这里硬编码 ``VERSION = "1.2.2"``，与 Claude 清单、CHANGELOG 三处各写一份，
    谁都不会发现不一致。`+codex.<token>` 后缀由 `tools/reinstall.py` 维护
    （宿主按版本号缓存插件），生成器只保留后缀、不重新发明基础版本。
    """
    try:
        data = json.loads(CLAUDE_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise SystemExit(f"读不到基础版本：{CLAUDE_MANIFEST}（{err}）")
    version = str(data.get("version") or "").strip()
    if not version:
        raise SystemExit(f"{CLAUDE_MANIFEST} 缺 version")
    return version

COMMAND_NAMES = (
    "setup",
    "generate",
    "audit",
    "review",
    "propose",
    "publish",
    "refresh",
    "status",
    "overview",
    "remember",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" 必须显式给：Windows 文本模式会把 \n 翻成 \r\n，与 `.gitattributes`
    # 规定的 LF 不一致，生成物会变成"显示已改、diff 却是空"的纯行尾噪声（实测踩过）。
    path.write_text(text, encoding="utf-8", newline="\n")
    print("wrote", path.relative_to(ROOT).as_posix())


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line and not line.startswith((" ", "-", "\t")):
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, text[end + 4 :].lstrip("\n")


def adapt_body(body: str) -> str:
    """把 Claude Code 专有写法翻译成 Codex 写法。"""
    for name in COMMAND_NAMES:
        body = re.sub(rf"(?<![\w/-])/kb-{name}\b", f"{SKILL_PREFIX}{name}", body)
    body = body.replace("$ARGUMENTS", "用户输入").replace("${ARGUMENTS}", "用户输入")
    body = body.replace(
        "AskUserQuestion",
        "向用户提问（Codex 里直接在对话中问，等用户回复，不要自答）",
    )
    body = body.replace(
        "`Task`",
        "子代理（Codex 用 spawn_agent 起子代理，或按 `skills/<角色>/SKILL.md` 的角色定义就地执行）",
    )
    return body


def build_command_skills() -> None:
    for name in COMMAND_NAMES:
        source = COMMANDS / f"{name}.md"
        if not source.is_file():
            print("skip (missing command):", source.name)
            continue
        meta, body = split_frontmatter(read(source))
        description = meta.get("description", f"/kb-{name} 命令（Codex 版入口技能）")
        header = (
            f"---\nname: {SKILL_PREFIX}{name}\ndescription: {description}"
            f"（Codex 入口，等价于 /kb-{name}）\n---\n\n"
            f"# {SKILL_PREFIX}{name}（Codex 版 `/kb-{name}`）\n\n"
            f"> 本文件由 `tools/build_codex_surface.py` 从 `commands/{name}.md` 生成，请勿手改；\n"
            f"> 改流程请改命令源文件后重跑生成器。命令里的 `py -3` 是 Windows 写法，\n"
            f"> macOS/Linux 换成 `python3`。\n\n"
        )
        write(SKILLS / f"{SKILL_PREFIX}{name}" / "SKILL.md", header + adapt_body(body).rstrip() + "\n")


def build_codex_hooks() -> None:
    """两宿主共用的 hook 配置（Codex 与 Claude Code 的 hook 契约相同）。"""
    claude = json.loads(read(HOOKS / "hooks.json") or "{}")
    config = {
        "description": (
            "knowledge-base-plugin 门控：PreToolUse 拦截未审计发布/同步、机器资产与 rules/ 直改，"
            "SessionStart 提示知识库状态。Claude Code 与 Codex 共用本文件；"
            "Windows 用 py -3，macOS/Linux 跑 tools/adapt_hooks.py 切到 python3。"
        ),
        "hooks": claude.get("hooks", {}),
    }
    write(HOOKS / "claude-codex-hooks.json", json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def build_codex_manifest() -> None:
    manifest_path = ROOT / ".codex-plugin" / "plugin.json"
    # 保留 tools/reinstall.py 写的 `+codex.<token>` 后缀，避免重跑生成器把它抹掉
    base = base_version()
    # 署名与许可也从 Claude 清单一处读：原先这里硬编码 author/license，
    # 换许可（MIT → Apache-2.0）时两份清单就对不上了——自检当场抓到过（KBP-027）。
    claude_manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    author = claude_manifest.get("author") or {"name": "AI实战技能圈"}
    license_id = str(claude_manifest.get("license") or "Apache-2.0").strip()
    version = base
    existing = read(manifest_path)
    if existing:
        try:
            current = str(json.loads(existing).get("version") or "")
        except json.JSONDecodeError:
            current = ""
        if "+" in current:
            version = f"{base}+{current.split('+', 1)[1]}"
    manifest = {
        "name": PLUGIN_NAME,
        "version": version,
        "description": (
            "数仓知识库生成流水线：采集(MCP 元数据)→结构化(业务骨架)→质检(冲突/断链/索引)"
            "→审阅(Owner 终签)→发布(git + OpenViking 双轨)→反哺(元数据回灌)→沉淀(规则提案)。"
        ),
        "author": author,
        "license": license_id,
        "keywords": ["knowledge-base", "data-warehouse", "openviking", "data-quality", "metadata"],
        "skills": "./skills/",
        "hooks": "./hooks/claude-codex-hooks.json",
        "interface": {
            "displayName": "Knowledge Base Pipeline",
            "shortDescription": "知识库七环节流水线 + 发布/审计硬门",
            "longDescription": (
                "把隐性、分散、易腐烂的数仓知识炼成版本化、可审计、可被 Agent 确定性消费的结构化事实。"
                "七环节各带机器门控与留证：审计不过不许发布，规则只能走提案，机器资产禁止手改。"
            ),
            "developerName": "AI实战技能圈",
            "category": "Productivity",
            "capabilities": ["Instructions", "Lifecycle hooks", "Write"],
            "defaultPrompt": [
                "初始化知识库项目并生成 user 域骨架",
                "跑一次 strict 审计，不通过就别发布",
                "把这条长期事实沉淀成规则提案",
            ],
            "brandColor": "#0E7C86",
        },
    }
    write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def build_agents_template() -> None:
    """Codex 读 AGENTS.md，Claude Code 读 CLAUDE.md —— 同一份规范两个文件名。"""
    claude_template = read(TEMPLATES / "CLAUDE.kb.md")
    if not claude_template:
        print("skip (missing template): engine/templates/CLAUDE.kb.md")
        return
    body = claude_template.replace(
        "# knowledge-base-plugin 知识库研发规范（由 /kb-setup 注入）",
        "# knowledge-base-plugin 知识库研发规范（由 kb-setup 注入；Codex 读 AGENTS.md）",
    )
    body = body.replace("AskUserQuestion", "向用户提问（Codex 里直接对话问）")
    write(TEMPLATES / "AGENTS.kb.md", body)


def main() -> int:
    build_codex_manifest()
    build_codex_hooks()
    build_command_skills()
    build_agents_template()
    print("\nCodex surface generated. Next: python tools/adapt_hooks.py (POSIX) / codex plugin add")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
