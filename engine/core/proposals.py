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
"""沉淀层：data-quality-kb-maintain 提案（不直接手改 rules/，必走提案）。

门禁：schema / 重复 / 冲突 / 单测 / 血缘（禁裸字段名横切）。
过门禁写库（status=APPLIED, final_status=READY_FOR_REVIEW）→ Owner approve → status=active。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import context, render, snapshot


def default_proposal(root: Path, domain: str) -> Dict[str, Any]:
    seq = context.next_seq(root, "proposal")
    return {
        "proposal_id": f"DQ-{context.utcnow()[:10].replace('-', '')}-{seq:03d}",
        "domain": domain,
        "created_at": context.utcnow(),
        "engine_gate": {"status": "PENDING", "issues": []},
        "final_status": "READY_FOR_REVIEW",
        "owner_review": None,
    }


def validate_proposal(proposal: Dict[str, Any], root: Path) -> List[str]:
    """五道门禁：schema / 重复 / 冲突 / 单测 / 血缘。"""
    problems: List[str] = []
    if not isinstance(proposal, dict):
        return ["提案必须是 JSON 对象"]
    rule = proposal.get("candidate_rule") or {}
    if not rule.get("id") or not rule.get("concept") or not rule.get("pattern"):
        problems.append("schema：candidate_rule 缺 id/concept/pattern")
    qualification = proposal.get("qualification") or {}
    five = [k for k, v in (qualification.get("five_gates") or {}).items() if v is not True]
    if five:
        problems.append(f"五资格判定未全过: {five}")
    domain = proposal.get("domain") or ""
    rule_id = str(rule.get("id", ""))
    # 重复：同 domain 同 pattern 已存在 active/APPLIED 规则
    rule_dir = context.rules_dir(root, domain)
    existing = []
    if rule_dir.is_dir():
        existing = [render.rule_yaml_parse(context.read_text(p)) for p in rule_dir.glob("*.yaml")]
    for ex in existing:
        if ex.get("pattern") == rule.get("pattern"):
            problems.append(f"重复：pattern={rule.get('pattern')} 已被规则 {ex.get('id')} 使用")
        if ex.get("id") == rule_id:
            problems.append(f"重复：rule id {rule_id} 已存在")
    # 冲突：同概念不同 pattern
    for ex in existing:
        if ex.get("concept") == rule.get("concept") and ex.get("pattern") != rule.get("pattern"):
            problems.append(
                f"冲突：概念「{rule.get('concept')}」已有规则 {ex.get('id')} pattern={ex.get('pattern')}，新提案 pattern 不一致"
            )
    # 单测：positive + negative 至少各 1
    tests = rule.get("tests") or {}
    if not (tests.get("positive") and tests.get("negative")):
        problems.append("单测：positive 与 negative 至少各 1 条（ambiguous 可选）")
    # 血缘：禁裸字段名横切——每个 lineage 表列必须能在元数据快照中找到
    lineage = rule.get("lineage") or []
    if not lineage:
        problems.append("血缘：必须带表血缘证据（table.column），禁止裸字段名横切")
    for item in lineage:
        table_id = str(item.get("table", ""))
        column = str(item.get("column", ""))
        row = snapshot.find_table(root, table_id)
        if row is None:
            problems.append(f"血缘：表 {table_id} 不在元数据快照中（先采集）")
            continue
        if column not in snapshot.column_names(row):
            problems.append(f"血缘：表 {table_id} 无字段 {column}")
    return problems


def apply_proposal(root: Path, proposal: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    # 提案号由引擎发：外部喂进来的 JSON 常常没有 proposal_id，旧实现直接拼出
    # `None.json`，随后 `rule approve --proposal-id <号>` 永远找不到它
    # （2026-10-07 在 data-warehouse-learning 上跑时实测）。
    if isinstance(proposal, dict) and not str(proposal.get("proposal_id") or "").strip():
        proposal["proposal_id"] = default_proposal(root, str(proposal.get("domain") or ""))["proposal_id"]
    problems = validate_proposal(proposal, root)
    if problems:
        proposal["engine_gate"] = {"status": "REJECTED", "issues": problems, "reason": reason}
        context.write_json(context.proposals_dir(root) / f"{proposal.get('proposal_id')}.json", proposal)
        return {"ok": False, "issues": problems, "proposal_id": proposal.get("proposal_id")}
    rule = dict(proposal["candidate_rule"])
    rule.setdefault("domain", proposal.get("domain"))
    rule["status"] = "APPLIED"
    rule["final_status"] = "READY_FOR_REVIEW"
    rule["owner"] = rule.get("owner") or (proposal.get("qualification") or {}).get("owner", "")
    rule["proposal"] = proposal.get("proposal_id")
    rule["created_at"] = proposal.get("created_at")
    context.ensure_dir(context.rules_dir(root, proposal.get("domain", "")))
    context.write_text(context.rules_dir(root, proposal.get("domain", "")) / f"{rule.get('id')}.yaml", render.rule_yaml_dump(rule))
    proposal["engine_gate"] = {"status": "APPLIED", "issues": [], "reason": reason}
    proposal["final_status"] = "READY_FOR_REVIEW"
    context.write_json(context.proposals_dir(root) / f"{proposal.get('proposal_id')}.json", proposal)
    return {"ok": True, "proposal_id": proposal.get("proposal_id"), "rule_id": rule.get("id"), "final_status": "READY_FOR_REVIEW"}


def approve_proposal(root: Path, proposal_id: str, owner: str, reason: str = "") -> Dict[str, Any]:
    proposal_path = context.proposals_dir(root) / f"{proposal_id}.json"
    proposal = context.load_json(proposal_path)
    if not isinstance(proposal, dict):
        return {"ok": False, "reason": f"提案不存在: {proposal_id}"}
    rule_id = str((proposal.get("candidate_rule") or {}).get("id", ""))
    rule_dir = context.rules_dir(root, proposal.get("domain", ""))
    rule_path = rule_dir / f"{rule_id}.yaml"
    if not rule_path.is_file():
        return {"ok": False, "reason": f"规则未落库（先过引擎门禁 APPLIED）: {rule_id}"}
    config = context.load_config(root)
    owners = config.get("owners") or {}
    if owner not in owners and owner not in owners.values():
        return {"ok": False, "reason": f"Owner {owner} 不在配置 owners 中（人工终签需登记 owner）"}
    rule = render.rule_yaml_parse(context.read_text(rule_path))
    if rule.get("owner") and rule.get("owner") not in (owner, owners.get(owner, owner)):
        return {"ok": False, "reason": f"规则 owner={rule.get('owner')} 与审批人 {owner} 不一致，禁止代签"}
    rule["status"] = "active"
    rule["final_status"] = "APPROVED"
    rule["reviewed_at"] = context.localnow()
    rule["reviewed_by"] = owner
    if reason:
        rule["review_reason"] = reason
    context.write_text(rule_path, render.rule_yaml_dump(rule))
    proposal["owner_review"] = {"owner": owner, "approved_at": context.localnow(), "reason": reason}
    proposal["final_status"] = "APPROVED"
    context.write_json(proposal_path, proposal)
    return {"ok": True, "rule_id": rule_id, "status": "active", "final_status": "APPROVED"}


def pending_proposals(root: Path) -> List[Dict[str, Any]]:
    out = []
    for path in sorted(context.proposals_dir(root).glob("*.json")):
        data = context.load_json(path)
        if isinstance(data, dict) and data.get("final_status") == "READY_FOR_REVIEW":
            out.append(data)
    return out
