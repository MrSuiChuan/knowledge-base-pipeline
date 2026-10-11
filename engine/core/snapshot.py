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
"""采集层：从平台 MCP 拉 6 类元数据，产出 metadata-snapshot.json（时间锚点，无臆造）。

6 类知识:
  BASIC_INFO        表基础信息（归属/负责人/行量/频率）
  COLUMN_BASIC_INFO 字段语义
  DDL_SQL           建表语句
  SCHEDULE_TASK     调度任务
  QUALITY_RULE      质量规则
  PARTITION_INFO    分区信息

来源有三种，由 ``source`` 决定，**不再写死**：

* ``mock``           读 ``.kb/mock/meta.json``（默认，开箱可体验）；
* ``platform-mcp``   调平台 metadata MCP CLI（config.cli.metadata），要求 JSON stdout；
* ``oss:<组件id>``   对主流实时处理组件做真实采集（见 ``core/sources.py`` 与
                     ``engine/sources/registry.json``）。

快照里的 ``source`` 字段如实记录本次来源；没在注册表登记的来源直接以
``source_unregistered`` 拦下，且**不落盘**——留证撒谎比没有留证更糟。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import context, sources

SIX_CATEGORIES = [
    "BASIC_INFO",
    "COLUMN_BASIC_INFO",
    "DDL_SQL",
    "SCHEDULE_TASK",
    "QUALITY_RULE",
    "PARTITION_INFO",
]


def _sample_meta() -> Dict[str, Any]:
    return {
        "tables": [
            {
                "schema": "dwd",
                "name": "dwd_user_di",
                "BASIC_INFO": {
                    "owner": "zhangsan",
                    "domain": "user",
                    "layer": "dwd",
                    "row_count": 1286400,
                    "frequency": "daily",
                    "comment": "用户域明细（日增量）",
                },
                "COLUMN_BASIC_INFO": [
                    {"column": "user_id", "comment": "用户ID（主键）", "data_type": "STRING", "is_primary_key": True},
                    {"column": "active_flag", "comment": "当日是否活跃（0/1）", "data_type": "BIGINT", "is_primary_key": False},
                    {"column": "active_ts", "comment": "当日最后一次活跃时间", "data_type": "DATETIME", "is_primary_key": False},
                ],
                "DDL_SQL": "CREATE TABLE dwd_user_di (user_id STRING COMMENT '用户ID', active_flag BIGINT COMMENT '当日是否活跃', active_ts DATETIME COMMENT '最后一次活跃时间') PARTITIONED BY (ds STRING);",
                "SCHEDULE_TASK": {"task_name": "dwd_user_di_di", "cron": "0 2 * * *", "owner": "zhangsan"},
                "QUALITY_RULE": [
                    {"rule": "pk_unique", "column": "user_id"},
                    {"rule": "not_null", "column": "user_id"},
                ],
                "PARTITION_INFO": {"partition_column": "ds", "type": "daily", "retention_days": 400},
            },
            {
                "schema": "ads",
                "name": "ads_user_act_di",
                "BASIC_INFO": {
                    "owner": "zhangsan",
                    "domain": "user",
                    "layer": "ads",
                    "row_count": 1286400,
                    "frequency": "daily",
                    "comment": "用户活跃日快照（ads）",
                },
                "COLUMN_BASIC_INFO": [
                    {"column": "user_id", "comment": "用户ID（主键）", "data_type": "STRING", "is_primary_key": True},
                    {"column": "active_flag", "comment": "当日是否活跃（0/1）", "data_type": "BIGINT", "is_primary_key": False},
                    {"column": "ds", "comment": "数据日期分区", "data_type": "STRING", "is_primary_key": False},
                ],
                "DDL_SQL": "CREATE TABLE ads_user_act_di (user_id STRING COMMENT '用户ID', active_flag BIGINT COMMENT '当日是否活跃') PARTITIONED BY (ds STRING);",
                "SCHEDULE_TASK": {"task_name": "ads_user_act_di", "cron": "0 4 * * *", "owner": "zhangsan"},
                "QUALITY_RULE": [
                    {"rule": "pk_unique", "column": "user_id"},
                    {"rule": "row_count_fluctuation", "threshold": 0.5},
                ],
                "PARTITION_INFO": {"partition_column": "ds", "type": "daily", "retention_days": 180},
            },
            {
                "schema": "dim",
                "name": "dim_date",
                "BASIC_INFO": {
                    "owner": "lisi",
                    "domain": "common",
                    "layer": "dim",
                    "row_count": 3660,
                    "frequency": "daily",
                    "comment": "日期维表",
                },
                "COLUMN_BASIC_INFO": [
                    {"column": "date_id", "comment": "日期ID yyyymmdd", "data_type": "STRING", "is_primary_key": True},
                    {"column": "is_workday", "comment": "是否工作日", "data_type": "BIGINT", "is_primary_key": False},
                ],
                "DDL_SQL": "CREATE TABLE dim_date (date_id STRING COMMENT '日期ID', is_workday BIGINT COMMENT '是否工作日') PARTITIONED BY (ds STRING);",
                "SCHEDULE_TASK": {"task_name": "dim_date", "cron": "0 1 * * *", "owner": "lisi"},
                "QUALITY_RULE": [{"rule": "pk_unique", "column": "date_id"}],
                "PARTITION_INFO": {"partition_column": "ds", "type": "daily", "retention_days": 500},
            },
        ]
    }


def meta_store_path(root: Path) -> Path:
    return root / context.APP_DIR_NAME / "mock" / "meta.json"


def ensure_meta_seeded(root: Path) -> Dict[str, Any]:
    path = meta_store_path(root)
    data = context.load_json(path)
    if not isinstance(data, dict) or not data.get("tables"):
        data = _sample_meta()
        context.write_json(path, data)
    return data


def resolve_source(config: Dict[str, Any], source: Optional[str] = None) -> str:
    """本次采集的来源：显式参数 > 项目配置 snapshot.source > 按 mode 的默认值。"""
    explicit = (source or "").strip()
    if explicit:
        return explicit
    configured = str(((config.get("snapshot") or {}).get("source")) or "").strip()
    if configured:
        return configured
    return "platform-mcp" if (config.get("mode") or "mock") == "live" else "mock"


def fetch_metadata(
    root: Path,
    domain: str,
    tables: Optional[List[str]] = None,
    source: Optional[str] = None,
    runner: Optional[Any] = None,
) -> Dict[str, Any]:
    """按来源拉元数据快照并落盘 metadata-snapshot-<ts>.json。返回快照内容。"""
    config = context.load_config(root)
    resolved = resolve_source(config, source)
    if resolved.startswith(sources.SOURCE_PREFIX):
        result = sources.collect(root, sources.parse_source(resolved), runner=runner)
        entries = result["entries"]
        resolved = result["source"]
    elif resolved == "platform-mcp":
        cli = str((config.get("cli") or {}).get("metadata", "metadata-mcp"))
        proc = subprocess.run(
            [cli, "snapshot", "--domain", domain] + (["--tables", ",".join(tables)] if tables else []),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"metadata MCP 拉取失败: {(proc.stderr or proc.stdout)[:500]}")
        raw = json.loads((proc.stdout or "").strip() or "{}")
        entries = raw.get("tables") if isinstance(raw, dict) else raw
    elif resolved == "mock":
        data = ensure_meta_seeded(root)
        entries = data.get("tables", [])
    else:
        raise sources.SourceError(
            "source_unregistered",
            f"未登记的采集来源：{resolved!r}（只认 mock / platform-mcp / oss:<组件id>；"
            "组件来源必须在 engine/sources/registry.json 里登记）",
            source=resolved,
        )
    snapshot = {
        "schema_version": 1,
        "generator": "domain-knowledge-generator",
        "domain": domain,
        "source": resolved,
        "generated_at": context.utcnow(),
        "categories": list(SIX_CATEGORIES),
        "tables": [],
    }
    for entry in entries:
        table_id = entry.get("table_id") or entry.get("name")
        if tables and table_id not in tables and entry.get("name") not in tables:
            continue
        row = {"schema": entry.get("schema"), "name": entry.get("name"), "table_id": table_id}
        for category in SIX_CATEGORIES:
            row[category] = entry.get(category, {})
        # 采集层的如实标注随行带进快照：不适用（NOT_APPLICABLE）、采失败（COLLECT_FAILED）、
        # 来源组件（_component）。它们不是第 7 类知识，是"这 6 类是怎么来的"的附注。
        for additive in (sources.NOT_APPLICABLE, sources.COLLECT_FAILED, "_component"):
            if entry.get(additive):
                row[additive] = entry[additive]
        snapshot["tables"].append(row)
    path = context.snapshot_dir(root) / f"metadata-snapshot-{context.utcnow().replace(':', '')}.json"
    context.write_json(path, snapshot)
    snapshot["_file"] = str(path)
    return snapshot


def touch_metadata(root: Path, table: str, category: str, field_path: str, value: Any) -> Dict[str, Any]:
    """模拟平台元数据漂移（mock 专用，用于反哺演示/测试）。"""
    data = ensure_meta_seeded(root)
    for entry in data["tables"]:
        if entry.get("name") == table or f"{entry.get('schema')}.{entry.get('name')}" == table:
            target = entry.get(category, {})
            if isinstance(target, dict) and field_path in target:
                old = target[field_path]
                target[field_path] = value
                context.write_json(meta_store_path(root), data)
                return {"ok": True, "table": table, "field": field_path, "old": old, "new": value}
            if category == "COLUMN_BASIC_INFO" and isinstance(target, list):
                column = field_path.split(".")[0]
                field = field_path.split(".")[1] if "." in field_path else "comment"
                for col in target:
                    if col.get("column") == column:
                        old = col.get(field)
                        col[field] = value
                        context.write_json(meta_store_path(root), data)
                        return {"ok": True, "table": table, "field": field_path, "old": old, "new": value}
    return {"ok": False, "error": f"未找到表/字段: {table} {category} {field_path}"}


# 统计类字段不参与漂移判定：它们是组件的运行计数，不是"知识"。
# 实测（2026-10-07，StarRocks）：information_schema.TABLES.TABLE_ROWS 会随统计信息刷新
# 在 3 与 0 之间抖动，若参与比对，每次反哺都会报一次"变了"并重写文档——
# 那是假漂移，会把反哺和发布门都变成噪声源。文档里照常展示，只是不当成事实变化。
VOLATILE_BASIC_FIELDS = ("row_count",)


def diff_snapshots(old: Dict[str, Any], new: Dict[str, Any]) -> List[Dict[str, Any]]:
    """识别元数据漂移（仅比 6 类中影响『基础身份/字段语义』的字段）。"""
    drift: List[Dict[str, Any]] = []
    old_tables = {t.get("table_id"): t for t in old.get("tables", [])}
    new_tables = {t.get("table_id"): t for t in new.get("tables", [])}
    for table_id, new_row in new_tables.items():
        old_row = old_tables.get(table_id)
        if old_row is None:
            drift.append({"table": table_id, "kind": "added", "changes": []})
            continue
        changes = []
        for category in ("BASIC_INFO", "COLUMN_BASIC_INFO"):
            old_cat, new_cat = old_row.get(category), new_row.get(category)
            if category == "BASIC_INFO":
                old_map = old_cat if isinstance(old_cat, dict) else {}
                new_map = new_cat if isinstance(new_cat, dict) else {}
                for key in sorted(set(old_map) | set(new_map)):
                    if key in VOLATILE_BASIC_FIELDS:
                        continue
                    if old_map.get(key) != new_map.get(key):
                        changes.append({"field": f"{category}.{key}", "old": old_map.get(key), "new": new_map.get(key)})
            else:
                old_cols = {c.get("column"): c for c in (old_cat or [])}
                new_cols = {c.get("column"): c for c in (new_cat or [])}
                for col in sorted(set(old_cols) | set(new_cols)):
                    if col not in old_cols:
                        changes.append({"field": f"{category}.{col}", "old": None, "new": "added"})
                    elif col not in new_cols:
                        changes.append({"field": f"{category}.{col}", "old": "removed", "new": None})
                    else:
                        for key in sorted(set(old_cols[col]) | set(new_cols[col])):
                            if old_cols[col].get(key) != new_cols[col].get(key):
                                changes.append(
                                    {
                                        "field": f"{category}.{col}.{key}",
                                        "old": old_cols[col].get(key),
                                        "new": new_cols[col].get(key),
                                    }
                                )
        if changes:
            drift.append({"table": table_id, "kind": "changed", "changes": changes})
    return drift


def latest_snapshot(root: Path) -> Optional[Dict[str, Any]]:
    files = sorted(context.snapshot_dir(root).glob("metadata-snapshot-*.json"))
    return context.load_json(files[-1]) if files else None


def find_table(root: Path, table_id: str) -> Optional[Dict[str, Any]]:
    snap = latest_snapshot(root)
    if snap:
        for row in snap.get("tables", []):
            if row.get("table_id") == table_id or row.get("name") == table_id:
                return row
    return None


def column_names(table_row: Dict[str, Any]) -> List[str]:
    cols = table_row.get("COLUMN_BASIC_INFO") or []
    return [str(c.get("column", "")) for c in cols if c.get("column")]
