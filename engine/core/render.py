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
"""渲染层：导航文档、9 章节表级文档、规则 YAML 的最小渲染/解析。

不引入第三方 YAML 依赖：只支持本插件自己产出的、扁平键 + 数组对象的子集。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import context

TABLE_DOC_SECTIONS = [
    "1 基础身份",
    "2 业务语境",
    "3 字段语义",
    "4 上游口径",
    "5 SQL 约束",
    "6 JOIN 关系",
    "7 FAQ",
    "8 质量 SLA",
    "9 检索关键词",
]


def navigation_markdown(domain: str, skeleton: Dict[str, Any]) -> str:
    lines = [
        f"# {domain} 域导航（navigation.md）",
        "",
        "> 生成器: domain-knowledge-generator · 推理纪律：场景内全表扫描，严禁因表名跳表；锚点表是找表入口。",
        "",
        "## 业务全景",
        "",
        str(skeleton.get("business_panorama", "")),
        "",
        f"scope: {skeleton.get('scope') or ''}",
        "",
        "## 实体与过程",
        "",
    ]
    for entity in skeleton.get("entities") or []:
        lines.append(f"- 实体 `{entity.get('name')}`: {entity.get('desc', '')}")
    lines.append("")
    for proc in skeleton.get("processes") or []:
        lines.append(f"- 过程 `{proc.get('name')}`: {proc.get('desc', '')}")
    lines += ["", "## 场景（锚点表 = 找表入口）", ""]
    for idx, sc in enumerate(skeleton.get("scenarios") or []):
        lines.append(
            f"{idx + 1}. **{sc.get('name')}** 锚点表: [{sc.get('anchor_table')}](tables/{sc.get('anchor_table')}.md) 范围: {', '.join(sc.get('scope_tables') or [])} goal: {sc.get('goal', '')}"
        )
    lines += ["", "## 规则（口径/命名/状态机）", ""]
    for idx, rule in enumerate(skeleton.get("rules") or []):
        lines.append(f"{idx + 1}. 概念「{rule.get('concept')}」= {rule.get('definition')}")
        if rule.get("scope"):
            lines.append(f"   - scope: {rule.get('scope')}")
    lines += ["", "## 数据层与目标", ""]
    for goal in skeleton.get("goals") or []:
        lines.append(
            f"- 目标「{goal.get('goal')}」→ 指标 {', '.join(goal.get('metrics') or [])} → 表 {', '.join(f'[{t}](tables/{t}.md)' for t in goal.get('tables') or [])}"
        )
    lines += ["", "## 检索关键词", ""]
    for key, values in (skeleton.get("keywords") or {}).items():
        lines.append(f"- {key}: {', '.join(values)}")
    lines.append("")
    return "\n".join(lines)


def _identity_block(table: Dict[str, Any]) -> str:
    basic = table.get("BASIC_INFO") or {}
    return "\n".join(f"- {key}: {value}" for key, value in basic.items()) or "- （无）"


def _collection_note_block(table: Dict[str, Any]) -> str:
    """采集附注：这一行的六类知识里，哪几类"不适用"、哪几类"没采到"，各带理由。

    附注本来就写在快照里（NOT_APPLICABLE / COLLECT_FAILED），但生成出来的表文档
    如果只是一片空白，读者会以为是"没字段"，而不是"消息组件没有字段这一层"。
    诚实标注的价值一半在写下来，另一半在让人看见。
    """
    lines: List[str] = []
    for category, reason in sorted((table.get("NOT_APPLICABLE") or {}).items()):
        lines.append(f"- {category}：不适用 —— {reason}")
    for category, reason in sorted((table.get("COLLECT_FAILED") or {}).items()):
        lines.append(f"- {category}：未采到 —— {reason}")
    if not lines:
        return ""
    return "\n\n**采集说明**（这一行的六类知识是怎么来的）\n\n" + "\n".join(lines)


def _fields_block(table: Dict[str, Any]) -> str:
    cols = table.get("COLUMN_BASIC_INFO") or []
    lines = ["| 字段 | 类型 | 语义 | 主键 |", "| --- | --- | --- | --- |"]
    for col in cols:
        lines.append(
            f"| {col.get('column')} | {col.get('data_type')} | {col.get('comment')} | {'PK' if col.get('is_primary_key') else ''} |"
        )
    return "\n".join(lines)


def table_doc_markdown(table_id: str, table: Dict[str, Any], note: Dict[str, Any]) -> str:
    basic = table.get("BASIC_INFO") or {}
    schedule = table.get("SCHEDULE_TASK") or {}
    quality = table.get("QUALITY_RULE") or []
    partition = table.get("PARTITION_INFO") or {}
    note = note or {}
    sections = {
        "1 基础身份": f"> 自动回灌（metadata BASIC_INFO）\n\n{_identity_block(table)}\n"
        f"- 调度: {schedule.get('task_name', '-')} {schedule.get('cron', '')}\n- 分区: {partition.get('partition_column')} / {partition.get('type')} / 保留 {partition.get('retention_days')} 天"
        f"{_collection_note_block(table)}",
        "2 业务语境": str(note.get("business_context") or "（人工维护：待补业务语境，含为什么建这张表）"),
        "3 字段语义": f"> 自动回灌（metadata COLUMN_BASIC_INFO）\n\n{_fields_block(table)}",
        "4 上游口径": "\n".join(f"- {item}" for item in note.get("upstream_calibers") or ["（待补：口径与上游一致性说明）"]),
        "5 SQL 约束": f"```sql\n{table.get('DDL_SQL', '')}\n```",
        "6 JOIN 关系": "\n".join(f"- [{item}]({item}.md)" for item in note.get("joins") or []) or "- （无 JOIN 或尚未人工补充）",
        "7 FAQ": "\n".join(f"- Q: {item.get('q')}\n  A: {item.get('a')}" for item in note.get("faq") or [{"q": "待补", "a": "待补"}]),
        "8 质量 SLA": "\n".join(f"- {q.get('rule')}@{q.get('column', '*')}" for q in quality) or "- （无质量规则）",
        "9 检索关键词": ", ".join(note.get("keywords") or [table_id, str(basic.get("comment", ""))]),
    }
    lines = [f"# {table_id}", ""]
    for section in TABLE_DOC_SECTIONS:
        lines.append(f"## {section}")
        lines.append("")
        lines.append(sections.get(section, ""))
        lines.append("")
    return "\n".join(lines)


def missing_sections(text: str) -> List[str]:
    return [s for s in TABLE_DOC_SECTIONS if f"## {s}" not in text]


def rule_yaml_dump(rule: Dict[str, Any]) -> str:
    """Render the rules/<domain>/<id>.yaml subset format."""
    lines = [f"id: {rule.get('id')}", f"domain: {rule.get('domain')}", f"concept: {rule.get('concept')}"]
    lines.append(f"pattern: {rule.get('pattern')}")
    lines.append(f"status: {rule.get('status')}")
    lines.append(f"final_status: {rule.get('final_status')}")
    lines.append(f"owner: {rule.get('owner')}")
    lines.append(f"proposal: {rule.get('proposal')}")
    lines.append(f"created_at: {rule.get('created_at')}")
    lines.append("lineage:")
    for item in rule.get("lineage") or []:
        lines.append(f"- table: {item.get('table')}")
        lines.append(f"  column: {item.get('column')}")
    lines.append("tests:")
    for bucket in ("positive", "negative", "ambiguous"):
        lines.append(f"  {bucket}:")
        for sample in rule.get("tests", {}).get(bucket) or []:
            lines.append(f"    - {sample}")
    lines.append("")
    return "\n".join(lines)


def rule_yaml_parse(text: str) -> Dict[str, Any]:
    rule: Dict[str, Any] = {"lineage": [], "tests": {"positive": [], "negative": [], "ambiguous": []}}
    section = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith(" ") and ":" in line and not line.startswith("-"):
            key, _, value = line.partition(":")
            value = value.strip()
            if value:
                rule[key.strip()] = value
            continue
        stripped = line.strip()
        if stripped.startswith("- table:"):
            entry = {"table": stripped.split(":", 1)[1].strip()}
            rule["lineage"].append(entry)
        elif stripped.startswith("- "):
            item = stripped[2:].strip()
            if section in rule["tests"]:
                rule["tests"][section].append(item)
            elif rule["lineage"]:
                pass
        elif stripped in ("positive", "negative", "ambiguous"):
            section = stripped
        elif stripped.startswith("column:"):
            if rule["lineage"]:
                rule["lineage"][-1]["column"] = stripped.split(":", 1)[1].strip()
    return rule


def domain_index_markdown(root: Path, domain: str) -> str:
    nav = context.read_text(context.domain_dir(root, domain) / "navigation.md")
    anchors = re.findall(r"\]\((tables/[^)]+\.md)\)", nav)
    lines = [
        f"# {domain} 域索引（index.md）",
        "",
        f"- 导航: [navigation.md](navigation.md)",
        f"- 表级文档: {len(anchors)}",
        "",
    ]
    for anchor in sorted(set(anchors)):
        lines.append(f"- {anchor}")
    lines.append("")
    return "\n".join(lines)


def rule_findings_from_markdown(root: Path, domain: str) -> List[Dict[str, str]]:
    """抽取‘概念=定义’口径对（用于冲突审计）。"""
    findings: List[Dict[str, str]] = []
    pattern = re.compile(r"概念[「『\"']([^」』\"']+)[」』\"'][^=]*=\s*([^\n（(]+)")
    nav = context.read_text(context.domain_dir(root, domain) / "navigation.md")
    for match in pattern.finditer(nav):
        findings.append({"concept": match.group(1).strip(), "definition": match.group(2).strip(), "source": "navigation.md"})
    tables_dir = context.tables_dir(root, domain)
    for path in sorted(tables_dir.glob("*.md")) if tables_dir.is_dir() else []:
        text = context.read_text(path)
        for match in pattern.finditer(text):
            findings.append({"concept": match.group(1).strip(), "definition": match.group(2).strip(), "source": path.name})
    return findings


def collect_md_links(text: str) -> List[str]:
    return re.findall(r"\]\(([^)#]+?)(?:#|\\)?\)", text)


def table_id_from_link(link: str) -> str:
    base = link.replace("tables/", "").replace(".md", "").strip()
    return base


def upstream_refs(text: str) -> List[str]:
    """从表级文档识别上游表引用（-- 上游: x 或 上游口径里的表名）。"""
    refs = []
    for match in re.finditer(r"(?:上游|upstream)[^\n:：]*[:：]\s*([^\n]+)", text, re.IGNORECASE):
        for token in re.split(r"[,，、\s]+", match.group(1).strip()):
            token = token.strip()
            if token and re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", token) and len(token) >= 5:
                refs.append(token)
    return refs
