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
"""结构化层：5 步交互产出的业务骨架（skeleton.json）schema 与校验。

步骤：
  1 业务全景        -> business_panorama / entities / scope
  2 实体与过程      -> processes
  3 场景            -> scenarios[].{name, anchor_table, scope_tables, goal}
  4 规则            -> rules[].{concept, definition, scope}
  5 数据层与目标    -> table_notes[].{table_id,...} / goals[].{goal, metrics, tables}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import context

STEP_KEYS = {
    1: {"business_panorama"},
    2: {"entities", "processes"},
    3: {"scenarios"},
    4: {"rules"},
    5: {"table_notes", "goals"},
}

REQUIRED_FOR_GENERATE = {"business_panorama", "entities", "processes", "scenarios", "rules", "goals"}


def empty_skeleton(domain: str) -> Dict[str, Any]:
    return {
        "domain": domain,
        "schema_version": 1,
        "steps_completed": [],
        "business_panorama": "",
        "scope": "",
        "entities": [],
        "processes": [],
        "scenarios": [],
        "rules": [],
        "table_notes": [],
        "goals": [],
        "keywords": {},
        "discipline": "场景内全表扫描，严禁因表名跳表；锚点表是找表入口，失准必须修正。",
    }


def skeleton_path(root: Path, domain: str) -> Path:
    return context.domain_dir(root, domain) / "skeleton.json"


def load(root: Path, domain: str) -> Dict[str, Any]:
    data = context.load_json(skeleton_path(root, domain))
    if not isinstance(data, dict):
        data = empty_skeleton(domain)
    data.setdefault("domain", domain)
    return data


def save(root: Path, domain: str, skeleton: Dict[str, Any]) -> None:
    context.write_json(skeleton_path(root, domain), skeleton)


def validate_step_fragment(step: int, fragment: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    keys = STEP_KEYS.get(int(step))
    if keys is None:
        problems.append(f"未知步骤 {step}（合法 1..5）")
        return problems
    if not isinstance(fragment, dict) or not any(k in fragment for k in keys):
        problems.append(f"步骤 {step} 产物必须包含 {sorted(keys)} 中的键")
        return problems
    if step == 1 and not str(fragment.get("business_panorama", "")).strip():
        problems.append("业务全景不能为空：抽取业务线主线（如 注册→活跃→留存）")
    if step == 3:
        for idx, sc in enumerate(fragment.get("scenarios") or []):
            if not sc.get("name") or not sc.get("anchor_table"):
                problems.append(f"场景 #{idx + 1} 缺 name/anchor_table（锚点表是找表入口）")
    if step == 4:
        for idx, rule in enumerate(fragment.get("rules") or []):
            if not rule.get("concept") or not rule.get("definition"):
                problems.append(f"规则 #{idx + 1} 缺 concept/definition")
    if step == 5:
        goals = fragment.get("goals") or []
        if not goals:
            problems.append("数据层与目标：至少一个 goal→metrics→tables 导航")
    return problems


def merge_fragment(root: Path, domain: str, step: int, fragment: Dict[str, Any]) -> Dict[str, Any]:
    problems = validate_step_fragment(step, fragment)
    if problems:
        raise ValueError("; ".join(problems))
    skeleton = load(root, domain)
    for key, value in fragment.items():
        if isinstance(value, list) and isinstance(skeleton.get(key), list):
            skeleton[key] = skeleton[key] + value
        else:
            skeleton[key] = value
    completed = set(skeleton.get("steps_completed") or [])
    completed.add(int(step))
    skeleton["steps_completed"] = sorted(completed)
    save(root, domain, skeleton)
    return skeleton


def validate_ready(skeleton: Dict[str, Any], snapshot_tables: List[str]) -> List[str]:
    problems: List[str] = []
    for key in sorted(REQUIRED_FOR_GENERATE):
        value = skeleton.get(key)
        if key == "business_panorama":
            if not str(value or "").strip():
                problems.append(f"缺 {key}")
        elif not value:
            problems.append(f"缺 {key}（至少非空）")
    scenarios = skeleton.get("scenarios") or []
    if not scenarios:
        problems.append("至少一个场景")
    known = set(snapshot_tables)
    for sc in scenarios:
        anchor = str(sc.get("anchor_table", ""))
        if anchor and anchor not in known:
            problems.append(f"场景锚点表 {anchor} 不在元数据快照中")
        for scope_table in sc.get("scope_tables") or []:
            if scope_table not in known:
                problems.append(f"场景 {sc.get('name')} 的范围表 {scope_table} 不在快照中")
    return problems
