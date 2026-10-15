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
"""质检层：口径冲突 + 六层断链 + 索引重建（生成即审计，不过不放行）。

审计结果写 ``<repo>/.kb-audit-<id>.json``（.gitignore 不入库；多人协作需重跑）。
稳定字段契约：generator / audit_level / mode / conflict_audit / link_audit /
index_rebuild / audit_scope。
"""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from . import context, render


@dataclass
class Issue:
    severity: str  # FAIL | WARN
    code: str
    message: str
    source: str = ""

    def __str__(self) -> str:
        return f"[{self.severity}] {self.code}{' @' + self.source if self.source else ''}: {self.message}"


def _link_target_exists(link: str, base_dir: Path) -> bool:
    target = (base_dir / link).resolve()
    return target.is_file()


def _six_layer_links(root: Path, domain: str, issues: List[Issue]) -> Dict[str, Any]:
    """六层链接完整性检测。

    L1 repo README -> domains/<d>/navigation.md
    L2 navigation.md 场景锚点 -> tables/*.md
    L3 navigation.md 目标导航 -> tables/*.md
    L4 表级文档 上游口径 -> 上游表文档存在
    L5 表级文档 JOIN 关系 -> join 表文档存在
    L6 表级文档 质量 SLA -> rules/<d>/ 规则 yaml 存在（按行引用）
    """
    domain_base = context.domain_dir(root, domain)
    tables_base = domain_base / "tables"
    layer_counts: Dict[str, Dict[str, Any]] = {}
    broken: List[str] = []

    readme = context.repo_dir(root) / "README.md"
    readme_links = render.collect_md_links(context.read_text(readme))
    nav_rel = f"domains/{domain}/navigation.md"
    layer_counts["L1_domain_index"] = {"scanned": len(readme_links), "broken": []}
    if nav_rel not in readme_links:
        broken.append(nav_rel)
        layer_counts["L1_domain_index"]["broken"].append(nav_rel)

    nav = context.read_text(domain_base / "navigation.md")
    nav_links = render.collect_md_links(nav)
    table_links = [link for link in nav_links if link.startswith("tables/")]
    missing_tables = [link for link in table_links if not (tables_base / Path(link).name).is_file()]
    layer_counts["L2_scenario_anchors"] = {"scanned": len(table_links), "broken": missing_tables}
    broken += missing_tables
    for link in missing_tables:
        issues.append(Issue("FAIL", "link.broken", f"导航锚点断链: {link}", source="navigation.md"))

    # L3/L4/L5/L6 per table doc
    total_md = 0
    total_links = 0
    for path in sorted(tables_base.glob("*.md")) if tables_base.is_dir() else []:
        total_md += 1
        text = context.read_text(path)
        for ref in render.upstream_refs(text):
            layer_counts.setdefault("L4_upstream", {"scanned": 0, "broken": []})
            layer_counts["L4_upstream"]["scanned"] += 1
            if not (tables_base / f"{ref}.md").is_file():
                broken.append(f"{path.name}->上游{ref}")
                layer_counts["L4_upstream"]["broken"].append(f"{path.name}->{ref}")
                issues.append(Issue("FAIL", "link.broken", f"上游表断链: {ref}", source=path.name))
        links = render.collect_md_links(text)
        total_links += len(links)
        join_broken = []
        for link in links:
            target = (tables_base / Path(link).name).resolve()
            if not target.is_file():
                join_broken.append(f"{path.name}->{link}")
        layer_counts.setdefault("L5_joins", {"scanned": 0, "broken": []})
        layer_counts["L5_joins"]["scanned"] += len(links)
        layer_counts["L5_joins"]["broken"] += join_broken
        broken += join_broken
        for item in join_broken:
            issues.append(Issue("FAIL", "link.broken", f"JOIN 断链: {item}", source=path.name))
        # L6 quality SLA references rule ids
        # 规则引用必须带分隔符（"规则: DQ-X" / "规则：DQ-X"）。旧写法 `规则:?[\s:：]*`
        # 会把中文词里的"规则"直接连上后面的英文，实测把真实 DDL 注释「活动规则ID」
        # 里的 "ID" 当成规则号，报一条不存在的断链（2026-10-07 在 data-warehouse-learning
        # 上跑通链路时被这条误报拦下）。
        for rule_ref in re.findall(r"规则\s*[:：]\s*([A-Z][A-Z0-9_-]+)", text):
            if not list(context.rules_dir(root, domain).glob(f"{rule_ref}.yaml")):
                broken.append(f"{path.name}->规则{rule_ref}")
                layer_counts.setdefault("L6_rules", {"scanned": 0, "broken": []})
                layer_counts["L6_rules"]["broken"].append(f"{path.name}->{rule_ref}")
                issues.append(Issue("FAIL", "link.broken", f"质量 SLA 引用的规则缺失: {rule_ref}", source=path.name))
    layer_counts.setdefault("L3_goals", {"scanned": len(nav_links), "broken": []})
    layer_counts.setdefault("L4_upstream", {"scanned": 0, "broken": []})
    layer_counts.setdefault("L6_rules", {"scanned": 0, "broken": []})
    return {
        "v41_six_layers": layer_counts,
        "total_md_scanned_v41": total_md,
        "total_links_scanned_v41": total_links,
        "broken": broken,
    }


def _conflict_audit(root: Path, domain: str, issues: List[Issue]) -> Dict[str, Any]:
    findings = render.rule_findings_from_markdown(root, domain)
    by_concept: Dict[str, List[Dict[str, str]]] = {}
    for finding in findings:
        by_concept.setdefault(finding["concept"], []).append(finding)
    conflicts = []
    for concept, entries in by_concept.items():
        definitions = {e["definition"] for e in entries}
        if len(definitions) > 1:
            conflicts.append(
                {
                    "concept": concept,
                    "definitions": sorted(definitions),
                    "sources": [e["source"] for e in entries],
                }
            )
            issues.append(
                Issue(
                    "FAIL",
                    "conflict.definition",
                    f"概念「{concept}」存在不同定义: {sorted(definitions)[:3]}",
                    source=",".join(e["source"] for e in entries),
                )
            )
    # 抽查：冲突审计附带 2 个确定性 spot check（导航锚点表存在于 tables/）
    nav = context.read_text(context.domain_dir(root, domain) / "navigation.md")
    table_links = [l for l in render.collect_md_links(nav) if l.startswith("tables/")]
    tables_base = context.tables_dir(root, domain)
    spot = []
    for link in table_links[: int(context.load_config(root).get("limits", {}).get("spot_checks", 2))]:
        ok = (tables_base / Path(link).name).is_file()
        spot.append({"link": link, "ok": ok})
    return {
        "findings": conflicts,
        "spot_check_results": {"checked": len(spot), "passed": sum(1 for s in spot if s["ok"]), "items": spot},
    }


def _index_rebuild(root: Path, domain: str) -> Dict[str, Any]:
    before = set((context.domain_dir(root, domain) / "index.md").read_text(encoding="utf-8").splitlines()) if (
        context.domain_dir(root, domain) / "index.md"
    ).is_file() else set()
    index_md = render.domain_index_markdown(root, domain)
    context.write_text(context.domain_dir(root, domain) / "index.md", index_md)
    after = set(index_md.splitlines())
    added = len(after - before)
    return {"updated": added, "skipped": 0}


def previous_broken_set(root: Path, domain: str) -> Set[str]:
    audits = sorted(context.repo_dir(root).glob(".kb-audit-*.json"))
    for audit_path in reversed(audits[:-1] if len(audits) > 1 else []):
        data = context.load_json(audit_path)
        if data and data.get("domain") == domain:
            return set((data.get("link_audit") or {}).get("broken") or [])
    return set()


def content_tree_hash(root: Path, domain: str) -> str:
    """Deterministic hash of the audited knowledge tree (domains + rules + README).

    走 ``context.sha256_file``（行尾归一到 LF）。直接按原始字节哈希的话，
    换机器或重新 checkout 导致的行尾变化会被判成"内容变了"——
    发布路径会以"内容哈希不一致，请重跑审计"拦住一次语义上毫无变化的知识树。
    """
    h = hashlib.sha256()
    paths: List[Path] = []
    domain_dir = context.domain_dir(root, domain)
    if domain_dir.is_dir():
        paths += [p for p in sorted(domain_dir.rglob("*")) if p.is_file()]
    rules_dir = context.rules_dir(root, domain)
    if rules_dir.is_dir():
        paths += [p for p in sorted(rules_dir.rglob("*")) if p.is_file()]
    readme = context.repo_dir(root) / "README.md"
    if readme.is_file():
        paths.append(readme)
    repo = context.repo_dir(root)
    for path in sorted(paths, key=lambda p: p.relative_to(repo).as_posix()):
        h.update(path.relative_to(repo).as_posix().encode("utf-8"))
        h.update(context.sha256_file(path).encode("ascii"))
    return h.hexdigest()


def run_audit(root: Path, domain: str, mode: str = "publish", level: str = "strict", generator: str = "domain-knowledge-generator") -> Dict[str, Any]:
    issues: List[Issue] = []
    conflict = _conflict_audit(root, domain, issues)
    link = _six_layer_links(root, domain, issues)
    previous = previous_broken_set(root, domain)
    current = set(link["broken"])
    link["changed_set_new_broken_introduced"] = sorted(current - previous)
    index = _index_rebuild(root, domain)
    scanned_dirs = sorted(p.relative_to(context.repo_dir(root)).as_posix() for p in [context.domain_dir(root, domain), context.rules_dir(root, domain)])
    audit_id = f"kb-audit-{context.utcnow()[:10]}-{context.next_seq(root, 'audit'):06d}"
    payload = {
        "generator": generator,
        "audit_id": audit_id,
        "domain": domain,
        "content_hash": content_tree_hash(root, domain),
        "audit_level": level,
        "mode": mode,
        "audit_scope": {
            "scanned_dirs": scanned_dirs,
            "total_md_scanned_v41": link["total_md_scanned_v41"],
            "total_links_scanned_v41": link["total_links_scanned_v41"],
        },
        "conflict_audit": conflict,
        "link_audit": {
            "v41_six_layers": link["v41_six_layers"],
            "changed_set_new_broken_introduced": link["changed_set_new_broken_introduced"],
            "broken": link["broken"],
        },
        "index_rebuild": index,
        "issues": [{"severity": i.severity, "code": i.code, "message": i.message, "source": i.source} for i in issues],
        "passed": not any(i.severity == "FAIL" for i in issues),
        "created_at": context.utcnow(),
    }
    context.write_audit_file(root, payload)
    state = context.load_state(root)
    state["last_audit"] = {
        "audit_id": audit_id,
        "passed": payload["passed"],
        "mode": mode,
        "level": level,
        "at": payload["created_at"],
        "content_hash": payload["content_hash"],
    }
    context.save_state(root, state)
    return payload


# 审计级别的严格程度排序：未登记的一律按最低（0）算，免得"没见过的级别"被当合格证据。
_LEVEL_STRICTNESS: Dict[str, int] = {"standard": 1, "strict": 2}


def _strictness(level: Any) -> int:
    return _LEVEL_STRICTNESS.get(str(level or "").strip().lower(), 0)


def audit_fresh_enough(root: Path) -> Dict[str, Any]:
    """publish 门用的最近审计检查：存在、passed、mode=publish、strict，且晚于最近内容变更。"""
    audit = context.latest_audit(root)
    if audit is None:
        return {"ok": False, "reason": "无审计记录：先运行 kbp audit --mode publish"}
    if not audit.get("passed"):
        return {"ok": False, "reason": f"最近审计未通过（{audit.get('audit_id')}），先修复冲突/断链"}
    if audit.get("mode") != "publish":
        return {"ok": False, "reason": f"最近审计不是 publish 模式（{audit.get('mode')}），先 kbp audit --mode publish"}
    required_level = context.load_config(root).get("audit_level", "strict")
    # 按「不低于配置要求」判，不按"必须完全相等"判：配置 standard 而审计跑了 strict，
    # 证据比要求的更严，判它不合格等于把更严的证据作废（2026-10-14 测试用例 K-18 实测）。
    if _strictness(audit.get("audit_level")) < _strictness(required_level):
        return {
            "ok": False,
            "reason": f"最近审计级别 {audit.get('audit_level')} 低于配置要求 {required_level}："
                      f"重跑 kbp audit --mode publish --level {required_level}",
        }
    audit_path = context.repo_dir(root) / f".kb-audit-{audit.get('audit_id')}.json"
    if not audit_path.is_file():
        return {"ok": False, "reason": "审计文件丢失，请重跑 audit"}
    stored = context.load_json(audit_path) or {}
    audited_hash = str(stored.get("content_hash") or "")
    if not audited_hash:
        return {"ok": False, "reason": "审计文件缺少 content_hash（旧版本），请重跑 kbp audit --mode publish"}
    if content_tree_hash(root, audit.get("domain") or stored.get("domain") or "") != audited_hash:
        return {"ok": False, "reason": "知识内容在最近审计后有变更（内容哈希不一致）：必须重跑 kbp audit --mode publish"}
    return {"ok": True, "audit_id": audit.get("audit_id")}
