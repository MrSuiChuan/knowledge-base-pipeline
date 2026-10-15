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
"""knowledge-base-plugin engine CLI.

把“生成知识库”跑成一条有门控的工艺流水线：
setup -> snapshot fetch -> skeleton(5步) -> generate -> audit -> rule propose/approve
-> publish(git+OV) -> refresh(反哺) -> re-audit -> publish v2 ...

Windows: py -3 engine/kbp.py <verb> ...    POSIX: python3 engine/kbp.py <verb> ...
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import (  # noqa: E402
    audit,
    context,
    gates,
    ov_memory,
    ov_remote,
    proposals,
    render,
    skeleton,
    snapshot,
    sources,
    sync,
)

# Windows 上 stdout/stderr 被重定向（管道、写文件、CI）时用 cp1252/cp936，
# HELP 与各种中文提示会直接 UnicodeEncodeError（实测 `--help` 就崩）。
# 交互式控制台走 PEP 528 的宽字符 API，本来就支持中文，这步是空操作。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT: Optional[Path] = None
CONFIG: Dict[str, Any] = {}


def parse_args(argv: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for i, token in enumerate(argv):
        if token.startswith("--"):
            key = token[2:]
            if "=" in key:
                k, v = key.split("=", 1)
                out[k] = v
            else:
                value = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else ""
                out[key] = value if value else "1"
        elif token.startswith("-") and len(token) > 1 and not token.startswith("--"):
            value = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else "1"
            out[token[1:]] = value
    return out


def boot(argv: List[str]) -> Dict[str, str]:
    global ROOT, CONFIG
    flags = parse_args(argv)
    root_arg = flags.get("root")
    if root_arg:
        ROOT = Path(root_arg).resolve()
    else:
        ROOT = context.project_root() or Path.cwd()
    CONFIG = context.load_config(ROOT) if (ROOT / context.APP_DIR_NAME / context.CONFIG_FILE).is_file() else context.default_config()
    mismatched = engine_selfcheck(ROOT)
    if mismatched:
        emit(
            {
                "ok": False,
                "blocked": True,
                "gate": "engine_integrity",
                "reason": ".kb/engine 与它自带的完整性清单不一致（被改写或未同步？）",
                "mismatched": mismatched,
            }
        )
        sys.exit(4)
    return flags


def engine_selfcheck(root: Path) -> List[str]:
    """核对项目内的引擎副本（``.kb/engine``）与它自带的完整性清单。

    * 没有 ``.kb/engine`` 或没有清单（未初始化的项目、直接跑插件根引擎）→ 返回空，不误报；
    * 返回非空 = 引擎文件被改过，调用方应当拒绝继续（fail-closed）。

    这不是沙箱：它只提高"偷偷改掉门控代码"的成本，并把改动变得可见。
    """
    engine_dir = root / context.APP_DIR_NAME / "engine"
    manifest_path = engine_dir / ".engine-manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = context.load_json(manifest_path, {}) or {}
    files = manifest.get("files") or {}
    mismatched: List[str] = []
    for rel, expected in sorted(files.items()):
        target = engine_dir / rel
        actual = context.sha256_file(target) if target.is_file() else "MISSING"
        if actual != expected:
            mismatched.append(rel)
    return mismatched


def emit(obj: Any) -> None:
    payload = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2)
    try:
        sys.stdout.buffer.write((payload + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
    except Exception:
        print(payload)


def domain(flags: Dict[str, str]) -> str:
    return str(flags.get("domain") or CONFIG.get("domain") or "user")


def verb_setup(flags: Dict[str, str]) -> None:
    mode = flags.get("mode", "mock")
    d = flags.get("domain", "user")
    context.ensure_app_dir(ROOT, mode=mode, domain=d)
    # 报"落盘后的实际配置"，不报这次请求的参数：重跑 setup 不再改动已有 config.json，
    # 把请求参数当结果报会与事实不符。
    config = context.load_config(ROOT)
    # 版本控制层的能力缺失必须在**安装期**说出来。旧实现把 _git_init 的结果丢掉，
    # git 不可用时 setup 照样报 ok，用户以为知识库已经版本化了，要到发布才被拦。
    vcs = context.vcs_status(ROOT)
    emit(
        {
            "ok": True,
            "root": str(ROOT),
            "mode": config.get("mode"),
            "domain": config.get("domain"),
            "vcs": vcs,
        }
    )


def verb_snapshot(flags: Dict[str, str]) -> None:
    sub = flags.get("sub", "")
    d = domain(flags)
    if sub == "fetch":
        tables = [t for t in flags.get("tables", "").split(",") if t.strip()] or None
        try:
            snap = snapshot.fetch_metadata(ROOT, d, tables, source=flags.get("source"))
        except sources.SourceError as exc:
            emit(exc.payload())
            sys.exit(3)
        emit({"ok": True, "tables": len(snap["tables"]), "source": snap.get("source"), "file": snap.get("_file")})
    elif sub == "touch":
        result = snapshot.touch_metadata(
            ROOT,
            flags.get("table", ""),
            flags.get("category", "BASIC_INFO"),
            flags.get("field", ""),
            _coerce(flags.get("value", "")),
        )
        emit(result)
        if not result.get("ok"):
            sys.exit(1)
    else:
        emit({"ok": True, "snapshot": snapshot.latest_snapshot(ROOT)})


def _component_flag(flags: Dict[str, str]) -> str:
    component_id = (flags.get("component") or "").strip()
    if not component_id:
        emit({"ok": False, "gate": "source_usage", "reason": "缺少 --component <组件id>；先跑 sources list 看有哪些"})
        sys.exit(2)
    return component_id


def verb_sources(flags: Dict[str, str]) -> None:
    """实时组件知识源：列注册表 / 探活 / 试采（试采不落盘，落盘走 snapshot fetch）。"""
    sub = (flags.get("sub") or "list").strip()
    if sub == "list":
        emit(
            {
                "ok": True,
                "registry": str(sources.registry_path()),
                "problems": sources.registry_errors(),
                "components": [sources.describe(item["id"]) for item in sources.components()],
            }
        )
        return
    if sub == "check":
        component_id = _component_flag(flags)
        try:
            result = sources.probe(ROOT, component_id)
        except sources.SourceError as exc:
            emit(exc.payload())
            sys.exit(3)
        emit(result)
        if not result.get("ok"):
            emit({"hint": f"组件没就绪：先按 docs/realtime-sources.md 的配方把它起起来，再跑 sources check {component_id}"})
            sys.exit(1)
        return
    if sub == "collect":
        component_id = _component_flag(flags)
        try:
            result = sources.collect(ROOT, component_id)
        except sources.SourceError as exc:
            emit(exc.payload())
            sys.exit(3)
        rows = result.pop("entries")
        summary = []
        for row in rows:
            summary.append(
                {
                    "table_id": row.get("table_id"),
                    "columns": len(row.get("COLUMN_BASIC_INFO") or []),
                    "not_applicable": sorted((row.get(sources.NOT_APPLICABLE) or {}).keys()),
                    "collect_failed": sorted((row.get(sources.COLLECT_FAILED) or {}).keys()),
                }
            )
        payload = dict(result)
        payload.update({"ok": True, "tables": len(rows), "tables_summary": summary})
        if flags.get("full"):
            payload["entries"] = rows
        emit(payload)
        return
    emit({"ok": False, "gate": "source_usage", "reason": f"不认识的子命令：{sub}（list / check / collect）"})
    sys.exit(2)


def _coerce(value: str) -> Any:
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        return int(value)
    except ValueError:
        return value


def _load_json_arg(flags: Dict[str, str]) -> Dict[str, Any]:
    path = Path(flags.get("json-file", ""))
    if not path.is_absolute():
        path = ROOT / path
    data = context.load_json(path)
    if not isinstance(data, dict):
        raise SystemExit(f"JSON 文件缺失或非法: {path}")
    return data


def verb_skeleton(flags: Dict[str, str]) -> None:
    sub = flags.get("sub", "")
    d = domain(flags)
    if sub == "step":
        step = int(flags.get("step", "0"))
        fragment = _load_json_arg(flags)
        try:
            merged = skeleton.merge_fragment(ROOT, d, step, fragment)
        except ValueError as exc:
            emit({"ok": False, "reason": str(exc)})
            sys.exit(1)
        emit({"ok": True, "steps_completed": merged["steps_completed"]})
    elif sub == "set":
        skeleton.save(ROOT, d, _load_json_arg(flags))
        emit({"ok": True, "path": str(skeleton.skeleton_path(ROOT, d))})
    elif sub == "validate":
        sk = skeleton.load(ROOT, d)
        snap = snapshot.latest_snapshot(ROOT) or {}
        known = [t.get("table_id") for t in snap.get("tables", [])]
        problems = skeleton.validate_ready(sk, known)
        emit({"ok": not problems, "problems": problems})
        if problems:
            sys.exit(1)
    else:
        sk = skeleton.load(ROOT, d)
        emit(sk)


def verb_generate(flags: Dict[str, str]) -> None:
    d = domain(flags)
    snap = snapshot.latest_snapshot(ROOT)
    if not snap:
        emit({"ok": False, "reason": "无元数据快照：先 snapshot fetch（采集铁律：不臆造）"})
        sys.exit(1)
    sk = skeleton.load(ROOT, d)
    known = [t.get("table_id") for t in snap.get("tables", [])]
    problems = skeleton.validate_ready(sk, known)
    if problems:
        emit({"ok": False, "reason": "skeleton 未就绪: " + "; ".join(problems)})
        sys.exit(1)
    context.ensure_dir(context.tables_dir(ROOT, d))
    context.write_text(context.domain_dir(ROOT, d) / "navigation.md", render.navigation_markdown(d, sk))
    notes = {n.get("table_id"): n for n in sk.get("table_notes") or []}
    written = []
    placeholders = []
    for table in snap.get("tables", []):
        table_id = table.get("table_id")
        doc = render.table_doc_markdown(table_id, table, notes.get(table_id) or {})
        context.write_text(context.tables_dir(ROOT, d) / f"{table_id}.md", doc)
        written.append(table_id)
        for section in render.missing_sections(doc):
            placeholders.append(f"{table_id} 缺章节 {section}")
        if "待补" in doc:
            placeholders.append(f"{table_id} 含待补占位")
    _ensure_repo_readme(ROOT, d)
    state = context.load_state(ROOT)
    state["last_generation"] = {"domain": d, "at": context.utcnow(), "tables": written}
    context.save_state(ROOT, state)
    emit({"ok": True, "domain": d, "written": written, "placeholder_warns": placeholders[:10], "placeholder_count": len(placeholders)})


def _ensure_repo_readme(root: Path, d: str) -> None:
    readme = context.repo_dir(root) / "README.md"
    text = context.read_text(readme)
    if not text.strip():
        text = "# Knowledge Base\n\n数仓知识库成品件仓库。知识 = 版本化、可审计、可被 Agent 消费的事实。\n\n## domains\n"
    link = f"domains/{d}/navigation.md"
    if link not in text:
        text += f"- [{d} 域]({link})\n"
    context.write_text(readme, text)


def verb_audit(flags: Dict[str, str]) -> None:
    d = domain(flags)
    mode = flags.get("mode", "publish")
    level = flags.get("level", str(CONFIG.get("audit_level", "strict")))
    result = audit.run_audit(ROOT, d, mode=mode, level=level)
    emit({"ok": result["passed"], "audit_id": result["audit_id"], "issues": result["issues"], "audit": result})
    if not result["passed"]:
        sys.exit(1)


def verb_propose(flags: Dict[str, str]) -> None:
    d = domain(flags)
    if flags.get("demo"):
        proposal = _demo_proposal(d)
    else:
        proposal = _load_json_arg(flags)
        proposal.setdefault("domain", d)
    result = proposals.apply_proposal(ROOT, proposal, flags.get("reason", ""))
    emit(result)
    if not result["ok"]:
        sys.exit(1)


def _demo_proposal(d: str) -> Dict[str, Any]:
    base = proposals.default_proposal(ROOT, d)
    base["title"] = "用户域 user_id 主键唯一性规则"
    base["domain"] = d
    base["qualification"] = {
        "owner": "zhangsan",
        "five_gates": {
            "跨需求成立": True,
            "长期成立": True,
            "可量化": True,
            "确定性匹配": True,
            "有证据": True,
        },
    }
    base["candidate_rule"] = {
        "id": "DQ-USER-PK-UNIQUE",
        "concept": "用户主键唯一",
        "pattern": "pk_unique(dwd_user_di.user_id)",
        "lineage": [{"table": "dwd_user_di", "column": "user_id"}],
        "tests": {
            "positive": ["dwd_user_di 内 user_id 去重计数 == 总行数"],
            "negative": ["存在重复 user_id 的记录（人工构造）"],
            "ambiguous": ["跨分区重复但单分区唯一（不算违规）"],
        },
        "owner": "zhangsan",
    }
    return base


def verb_rule(flags: Dict[str, str]) -> None:
    sub = flags.get("sub", "")
    if sub == "approve":
        result = proposals.approve_proposal(ROOT, flags.get("proposal-id", ""), flags.get("owner", ""), flags.get("reason", ""))
        emit(result)
        if not result["ok"]:
            sys.exit(1)
    elif sub == "list":
        d = domain(flags)
        items = []
        rule_dir = context.rules_dir(ROOT, d)
        if rule_dir.is_dir():
            for path in sorted(rule_dir.glob("*.yaml")):
                rule = render.rule_yaml_parse(context.read_text(path))
                items.append({k: rule.get(k) for k in ("id", "concept", "pattern", "status", "final_status", "owner", "proposal")})
        emit({"rules": items, "pending_review": len(proposals.pending_proposals(ROOT))})
    else:
        emit({"ok": False, "reason": "rule 子命令: list|approve"})
        sys.exit(1)


def verb_review(flags: Dict[str, str]) -> None:
    pending = proposals.pending_proposals(ROOT)
    emit(
        {
            "pending": [
                {
                    "proposal_id": p.get("proposal_id"),
                    "domain": p.get("domain"),
                    "title": p.get("title"),
                    "engine_gate": (p.get("engine_gate") or {}).get("status"),
                    "final_status": p.get("final_status"),
                    "rule_id": (p.get("candidate_rule") or {}).get("id"),
                }
                for p in pending
            ],
            "note": "引擎门禁 APPLIED ≠ Owner 终签：请逐条 approve，收口治理窗口。",
        }
    )


def verb_publish(flags: Dict[str, str]) -> None:
    d = domain(flags)
    consumer = Path(flags["consumer-root"]) if flags.get("consumer-root") else None
    result = sync.publish(ROOT, d, flags.get("reason", ""), consumer_root=consumer)
    emit(result)
    if not result["ok"]:
        sys.exit(1)


def verb_refresh(flags: Dict[str, str]) -> None:
    d = domain(flags)
    previous = snapshot.latest_snapshot(ROOT)
    if previous is None:
        emit({"ok": False, "reason": "无旧快照可比对：先 snapshot fetch 一次作为基线"})
        sys.exit(1)
    old_tables = {t.get("table_id"): t for t in previous.get("tables", [])}
    new_snap = snapshot.fetch_metadata(ROOT, d)
    drift = snapshot.diff_snapshots(previous, new_snap)
    rewritten = []
    sk = skeleton.load(ROOT, d)
    notes = {n.get("table_id"): n for n in sk.get("table_notes") or []}
    for change in drift:
        table_id = change.get("table")
        row = next((t for t in new_snap.get("tables", []) if t.get("table_id") == table_id), None)
        if row is None:
            continue
        changed_fields = [c.get("field") for c in change.get("changes", [])]
        if any(f.startswith(("BASIC_INFO", "COLUMN_BASIC_INFO")) for f in changed_fields):
            context.write_text(context.tables_dir(ROOT, d) / f"{table_id}.md", render.table_doc_markdown(table_id, row, notes.get(table_id) or {}))
            rewritten.append(table_id)
    drift_path = context.runtime_dir(ROOT) / f"refresh-drift-{context.utcnow().replace(':', '')}.json"
    context.write_json(
        drift_path,
        {
            "domain": d,
            "drift": drift,
            "rewritten": rewritten,
            "note": "反哺只回灌元数据可确定部分（基础身份/字段语义）；业务语境/SQL约束/FAQ 靠人。改动后必须重跑 audit 再 publish。",
        },
    )
    state = context.load_state(ROOT)
    state["last_refresh"] = {"domain": d, "at": context.utcnow(), "drift_count": len(drift), "rewritten": rewritten}
    context.save_state(ROOT, state)
    emit({"ok": True, "drift": drift, "rewritten": rewritten, "report": str(drift_path)})


def _fail_memory(exc: Exception) -> None:
    """把会话记忆链路上的三类失败统一成同一形状的载荷（gate + reason）。"""
    if isinstance(exc, ov_memory.MemoryError):
        emit(exc.payload())
    elif isinstance(exc, ov_remote.OVConfigError):
        emit({"ok": False, "blocked": True, "gate": "ov_config", "reason": str(exc)})
    elif isinstance(exc, ov_remote.OVRemoteError):
        emit({"ok": False, "blocked": True, "gate": exc.code, "reason": exc.message, "http_status": exc.http_status})
    else:  # pragma: no cover - 兜底：不吞异常信息
        emit({"ok": False, "blocked": True, "gate": "memory_error", "reason": str(exc)})
    sys.exit(3)


def verb_memory(flags: Dict[str, str]) -> None:
    """会话记忆：把一次会话记进 OpenViking，并在 commit 时触发记忆抽取。

    与发布链路的分工：``publish`` 把**定稿知识**写进 ``viking://resources/``；
    这里记的是**会话本身**，抽取出来的记忆落在 user/agent 的记忆目录。两条路互不替代。
    """
    sub = (flags.get("sub") or "status").strip()
    try:
        if sub == "begin":
            emit(ov_memory.begin(ROOT, flags.get("session") or None))
            return
        if sub == "add":
            role = (flags.get("role") or "user").strip()
            content = flags.get("content") or ""
            if flags.get("file"):
                content = context.read_text(Path(flags["file"]))
            if not content.strip():
                emit({"ok": False, "gate": "memory_usage", "reason": "缺少内容：用 --content <文本> 或 --file <路径>"})
                sys.exit(2)
            emit(ov_memory.append(ROOT, role, content))
            return
        if sub == "batch":
            path = flags.get("json-file") or flags.get("file")
            if not path:
                emit({"ok": False, "gate": "memory_usage", "reason": "缺少 --json-file <路径>（内容为 {messages:[...]} 或直接一个数组）"})
                sys.exit(2)
            data = context.load_json(Path(path), None)
            messages = data.get("messages") if isinstance(data, dict) else data
            if not isinstance(messages, list) or not messages:
                emit({"ok": False, "gate": "memory_usage", "reason": f"消息列表为空或形状不对：{path}"})
                sys.exit(2)
            emit(ov_memory.append_many(ROOT, messages))
            return
        if sub == "commit":
            keep_raw = flags.get("keep-recent")
            keep = int(keep_raw) if keep_raw else None
            emit(ov_memory.commit(ROOT, keep_recent_count=keep, wait=not flags.get("no-wait")))
            return
        if sub == "used":
            uris = [u.strip() for u in (flags.get("uris") or "").split(",") if u.strip()]
            emit(ov_memory.mark_used(ROOT, contexts=uris or None))
            return
        if sub == "status":
            emit(ov_memory.status(ROOT))
            return
        emit({"ok": False, "gate": "memory_usage", "reason": f"不认识的子命令：{sub}（begin / add / batch / commit / used / status）"})
        sys.exit(2)
    except (ov_memory.MemoryError, ov_remote.OVConfigError, ov_remote.OVRemoteError) as exc:
        _fail_memory(exc)


def verb_status(flags: Dict[str, str]) -> None:
    state = context.load_state(ROOT)
    audit_state = state.get("last_audit") or {}
    publish_state = state.get("last_publish") or {}
    generation_state = state.get("last_generation") or {}
    d = domain(flags)
    rule_dir = context.rules_dir(ROOT, d)
    rules = []
    if rule_dir.is_dir():
        for path in sorted(rule_dir.glob("*.yaml")):
            rule = render.rule_yaml_parse(context.read_text(path))
            rules.append({"id": rule.get("id"), "status": rule.get("status"), "final_status": rule.get("final_status"), "owner": rule.get("owner")})
    manifest = context.load_json(context.repo_dir(ROOT) / ".kb-manifest.json", {"publishes": []})
    emit(
        {
            "domain": d,
            "mode": CONFIG.get("mode"),
            "ov": {
                "remote_enabled": bool((CONFIG.get("ov") or {}).get("remote_enabled")),
                "url": (CONFIG.get("ov") or {}).get("url", ""),
                "configured": bool((CONFIG.get("ov") or {}).get("url"))
                and bool((CONFIG.get("ov") or {}).get("api_key_env") or (CONFIG.get("ov") or {}).get("api_key_file")),
                "note": "密钥不落盘；api_key_env / api_key_file 只标注来源，不输出内容",
            },
            "last_generation": generation_state,
            "last_audit": audit_state,
            "last_publish": publish_state,
            "publish_count": len(manifest.get("publishes", [])),
            "rules": rules,
            "pending_review": len(proposals.pending_proposals(ROOT)),
            "context": state.get("context", {}),
        }
    )


def verb_ov_check(flags: Dict[str, str]) -> None:
    from core import ov_remote

    result = ov_remote.check_connection(CONFIG)
    emit(result)
    if not result.get("ok"):
        sys.exit(2)


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------
def _demo_skeleton(d: str) -> Dict[str, Any]:
    return {
        "domain": d,
        "steps_completed": [1, 2, 3, 4, 5],
        "business_panorama": "注册 → 活跃 → 留存 → 回访：按日产出活跃画像与指标",
        "scope": "用户域日活/活跃口径与质量规则",
        "entities": [{"name": "user", "desc": "平台用户"}],
        "processes": [
            {"name": "注册", "desc": "用户创建账号"},
            {"name": "活跃", "desc": "当日发生任意行为即活跃"},
        ],
        "scenarios": [
            {
                "name": "活跃统计",
                "anchor_table": "dwd_user_di",
                "scope_tables": ["dwd_user_di"],
                "goal": "UV 与活跃标志的一致产出",
            }
        ],
        "rules": [{"concept": "活跃", "definition": "当日有任意行为即活跃", "scope": "user"}],
        "table_notes": [
            {
                "table_id": "dwd_user_di",
                "business_context": "用户域日增量明细，活跃判断的事实源头",
                "upstream_calibers": ["概念「活跃」= 当日有任意行为即活跃"],
                "joins": [],
                "faq": [{"q": "活跃口径与 active_flag 的关系？", "a": "active_flag=1 表示当日活跃"}],
                "keywords": ["用户", "活跃", "dwd", "明细"],
            },
            {
                "table_id": "ads_user_act_di",
                "business_context": "用户活跃日快照，供报表/指标消费",
                "upstream_calibers": ["概念「活跃」= 当日有任意行为即活跃"],
                "joins": ["dwd_user_di"],
                "faq": [{"q": "与 dwd 明细的差异？", "a": "ads 是清洗后快照，dwd 是明细"}],
                "keywords": ["活跃快照", "ads"],
            },
        ],
        "goals": [
            {
                "goal": "用户活跃监控",
                "metrics": ["uv", "活跃率"],
                "tables": ["dwd_user_di", "ads_user_act_di"],
            }
        ],
        "keywords": {"用户": ["dwd_user_di", "ads_user_act_di"], "日期": ["dim_date"]},
        "discipline": "场景内全表扫描，严禁因表名跳表；锚点表是找表入口。",
    }


def verb_demo(flags: Dict[str, str]) -> None:
    mode = CONFIG.get("mode") or flags.get("mode", "mock")
    if mode != "mock":
        emit({"ok": False, "reason": "demo 只支持 mock 模式"})
        sys.exit(2)
    steps: List[Dict[str, str]] = []
    log = lambda gate, msg: steps.append({"gate": gate, "msg": msg})
    d = domain(flags)

    verb_setup({"mode": "mock", "domain": d})
    log("setup", f"初始化 .kb（mode=mock, domain={d}）")
    verb_snapshot({"sub": "fetch", "domain": d})
    log("capture", "采集：MCP 6 类元数据 -> metadata-snapshot.json（无臆造）")
    skeleton.save(ROOT, d, _demo_skeleton(d))
    verb_skeleton({"sub": "validate", "domain": d})
    verb_generate({"domain": d})
    log("structure", "结构化：5 步骨架 -> navigation.md + 9 章节表级文档")
    verb_audit({"domain": d, "mode": "publish", "level": "strict"})
    log("audit", "质检：口径冲突/六层断链/索引重建 passed（publish/strict）")
    verb_propose({"domain": d, "demo": "1"})
    log("propose", "沉淀：提案过引擎门禁（schema/重复/冲突/单测/血缘），写库 APPLIED + READY_FOR_REVIEW")
    verb_rule({"sub": "list", "domain": d})
    log("review-window", "⚠ APPLIED≠REVIEWED 中间态可见：Owner 未签前规则已被运行时潜在消费")
    pending = proposals.pending_proposals(ROOT)
    verb_rule(
        {
            "sub": "approve",
            "domain": d,
            "proposal-id": pending[0]["proposal_id"] if pending else "",
            "owner": "zhangsan",
            "reason": "用户域 Owner 终签",
        }
    )
    log("review", "审阅：Owner zhangsan approve -> status=active")
    verb_audit({"domain": d, "mode": "publish", "level": "strict"})
    log("re-audit-1", "沉淀落库后复审（publish 门要求审计新鲜度）")
    verb_publish({"domain": d, "reason": "知识库 v1：用户域知识发布"})
    log("publish-v1", "发布：git 入库 + OpenViking 同步 + .kb-manifest.json（guard 通过）")
    result = snapshot.touch_metadata(ROOT, "dwd_user_di", "COLUMN_BASIC_INFO", "active_flag.comment", "当日是否活跃（0/1，2026 口径修订）")
    log("drift", f"平台元数据漂移：{result.get('field')} -> {result.get('new')}")
    verb_refresh({"domain": d})
    log("refresh", "反哺：快照比对 -> 回灌 基础身份/字段语义 -> drift report")
    verb_audit({"domain": d, "mode": "publish", "level": "strict"})
    log("re-audit", "反哺后重跑质检通过")
    verb_publish({"domain": d, "reason": "反哺闭环 v2：字段口径漂移已回灌"})
    log("publish-v2", "发布 v2：反哺闭环完成（元数据变化 -> 知识保鲜）")
    state = context.load_state(ROOT)
    manifest = context.load_json(context.repo_dir(ROOT) / ".kb-manifest.json", {"publishes": []})
    emit(
        {
            "ok": True,
            "domain": d,
            "publish_count": len(manifest.get("publishes", [])),
            "versions": [p.get("version") for p in manifest.get("publishes", [])],
            "last_audit": state.get("last_audit"),
            "steps": steps,
        }
    )


HELP = """knowledge-base-plugin engine

verbs:
  setup [--mode mock|live] [--domain user|common]
  snapshot fetch [--domain d] [--tables a,b] [--source <来源>] | touch --table t --category BASIC_INFO --field f --value v | show
                                        # 来源可取 mock | platform-mcp | oss:<组件id>；不传则用
                                        # .kb/config.json 的 snapshot.source，再按 mode 兜底
  sources list                          # 实时组件注册表：谁、什么角色、采集器、验证到哪一层
  sources check --component oss_kafka   # 就绪探测（按注册表声明的探法，探不通即非零退出）
  sources collect --component oss_kafka [--full]
                                        # 试采但不落盘；落盘走 snapshot fetch --source oss:<组件id>
  skeleton new|show|set --json-file f | step --step 1..5 --json-file f | validate [--domain d]
  generate [--domain d]                  # 5 步骨架 + 快照 -> navigation + 9 章节表文档
  audit [--domain d] [--mode publish|local] [--level strict|standard]
  rule list [--domain d] | approve --proposal-id DQ-... --owner zhangsan --reason ...
  review list
  propose --json-file f [--domain d] | --demo
  publish [--domain d] --reason ... [--consumer-root <data-dev 项目根>]
  refresh [--domain d]                   # 反哺：回灌身份/字段 + drift report
  ov-check                               # 真实 OpenViking 连通性/鉴权自检（只读）
  memory begin [--session <id>]          # 建会话并绑定到本项目（.kb/runtime/memory/session.json）
  memory add --role user|assistant --content <文本> | --file <路径>
  memory batch --json-file <路径>         # 批量追加（服务端上限 100 条/次，自动分批）
  memory commit [--keep-recent N] [--no-wait]
                                         # 归档 + 触发记忆抽取（消耗模型配额）；默认等到任务终态
  memory used --uris <viking://a,viking://b>   # 记录本次用到了哪些上下文
  memory status                          # 回读服务端会话：message_count / memories_extracted
  status [--domain d]
  demo [--domain user]

global: --root <project-dir>
"""


def main() -> None:
    tokens = sys.argv[1:]
    if not tokens or tokens[0] in ("--help", "-h", "help"):
        print(HELP)
        return
    known = {"setup", "snapshot", "sources", "skeleton", "generate", "audit", "rule", "review", "propose", "publish", "refresh", "ov-check", "memory", "status", "demo"}
    verb_index = next((i for i, token in enumerate(tokens) if token in known), None)
    if verb_index is None:
        print(HELP, file=sys.stderr)
        sys.exit(2)
    verb = tokens[verb_index]
    flags = boot(tokens)
    sub = next((token for token in tokens[verb_index + 1 :] if not token.startswith("-")), None)
    if sub and verb in ("snapshot", "sources", "skeleton", "rule", "memory"):
        flags["sub"] = sub
    handlers: Dict[str, Callable[[Dict[str, str]], None]] = {
        "setup": verb_setup,
        "snapshot": verb_snapshot,
        "sources": verb_sources,
        "skeleton": verb_skeleton,
        "generate": verb_generate,
        "audit": verb_audit,
        "rule": verb_rule,
        "review": verb_review,
        "propose": verb_propose,
        "publish": verb_publish,
        "refresh": verb_refresh,
        "ov-check": verb_ov_check,
        "memory": verb_memory,
        "status": verb_status,
        "demo": verb_demo,
    }
    handlers[verb](flags)


if __name__ == "__main__":
    main()
