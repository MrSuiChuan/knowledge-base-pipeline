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
"""实时组件知识源：把主流实时处理组件的元数据翻译成 6 类知识契约。

三条设计纪律，都是为了"不撒谎"：

1. **注册表是唯一事实源**：谁、什么角色、用哪个采集器、需要哪些连接键、本机验证到哪一层，
   只写 ``engine/sources/registry.json``。连接信息（装在哪、地址是什么）来自项目级
   ``.kb/config.json`` 的 ``sources.<组件id>``，包里不写死任何主机名与路径。
2. **区分"不适用"与"采失败"**：不适用于该组件的类别写进行级 ``NOT_APPLICABLE``，
   采不到的写 ``COLLECT_FAILED``。类别值本身按契约类型留空（dict→{} / list→[] / str→""），
   绝不塞假数据——"空"和"编"是两回事。
3. **外部命令可注入**：真跑走 ``subprocess``（支持 WSL 前缀），单测注入桩函数，
   不依赖本机有没有装这个组件。
"""

from __future__ import annotations

import json
import re
import shlex
import socket
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import context

REGISTRY_REL = ("sources", "registry.json")
NOT_APPLICABLE = "NOT_APPLICABLE"
COLLECT_FAILED = "COLLECT_FAILED"

SOURCE_PREFIX = "oss:"


class SourceError(RuntimeError):
    """采集层的失败。``gate`` 直接进机器的门控键，不做二次包装。"""

    def __init__(self, gate: str, reason: str, **extra: Any) -> None:
        super().__init__(reason)
        self.gate = gate
        self.reason = reason
        self.extra = extra

    def payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"ok": False, "blocked": True, "gate": self.gate, "reason": self.reason}
        payload.update(self.extra)
        return payload


def registry_path() -> Path:
    """注册表随引擎走：``engine/core/sources.py`` → ``engine/sources/registry.json``。"""
    return Path(__file__).resolve().parent.parent.joinpath(*REGISTRY_REL)


_REGISTRY_CACHE: Optional[Dict[str, Any]] = None


def load_registry(force: bool = False) -> Dict[str, Any]:
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None or force:
        path = registry_path()
        data = context.load_json(path, None)
        if not isinstance(data, dict) or not data.get("components"):
            raise SourceError("source_registry_missing", f"读不到组件注册表或它为空：{path}")
        _REGISTRY_CACHE = data
    return _REGISTRY_CACHE


def components() -> List[Dict[str, Any]]:
    return list(load_registry().get("components") or [])


def component(component_id: str) -> Optional[Dict[str, Any]]:
    for item in components():
        if item.get("id") == component_id:
            return item
    return None


def contract_categories() -> List[str]:
    """6 类知识的固定顺序，取自注册表——不在这里再抄一份。"""
    return list((load_registry().get("categories") or {}).keys())


def parse_source(raw: str) -> str:
    """``oss:oss_kafka`` → ``oss_kafka``；不是组件来源就抛错（只认这一种前缀）。"""
    text = (raw or "").strip()
    if not text.startswith(SOURCE_PREFIX):
        raise SourceError("source_unknown", f"不认识的来源写法：{raw!r}（组件来源要写 {SOURCE_PREFIX}<组件id>）")
    component_id = text[len(SOURCE_PREFIX) :].strip()
    if not component_id:
        raise SourceError("source_unknown", f"来源缺少组件 id：{raw!r}")
    return component_id


def registry_errors() -> List[str]:
    """注册表自检：只报形状问题，不做"假装支持"之外的判断。"""
    problems: List[str] = []
    try:
        data = load_registry()
    except SourceError as exc:
        return [exc.reason]
    ids: List[str] = []
    for item in data.get("components") or []:
        cid = item.get("id")
        if not cid:
            problems.append("有组件缺 id")
            continue
        if cid in ids:
            problems.append(f"组件 id 重复：{cid}")
        ids.append(cid)
        if item.get("tier") not in (1, 2, 3):
            problems.append(f"{cid}: tier 只能是 1/2/3")
        collector = item.get("collector")
        if collector and collector not in COLLECTORS:
            problems.append(f"{cid}: 登记了采集器 {collector}，但引擎里没有这个实现")
        if not collector and item.get("tier") != 3:
            problems.append(f"{cid}: 没有采集器却标成 tier {item.get('tier')}（只登记形状的应当是 tier 3）")
        if collector and item.get("tier") == 3:
            problems.append(f"{cid}: 有采集器就不该是 tier 3")
        coverage = item.get("coverage") or {}
        for category in contract_categories():
            if coverage.get(category) not in ("collect", "not_applicable"):
                problems.append(f"{cid}: 类别 {category} 没有声明 collect / not_applicable")
        reasons = item.get("not_applicable_reasons") or {}
        for category, mode in coverage.items():
            if mode == "not_applicable" and not reasons.get(category):
                problems.append(f"{cid}: 类别 {category} 标了 not_applicable 却没写理由")
        if item.get("tier") == 1 and not item.get("verified"):
            problems.append(f"{cid}: 标成已真跑的 tier 1，却没有验证记录")
        if item.get("tier") != 1 and item.get("verified"):
            problems.append(f"{cid}: tier {item.get('tier')} 不该带验证记录")
    return problems


# --------------------------------------------------------------------------------------
# 连接配置与就绪探测
# --------------------------------------------------------------------------------------


def source_config(root: Path, component_id: str) -> Dict[str, Any]:
    config = context.load_config(root)
    bucket = (config.get("sources") or {}).get(component_id) or {}
    if not isinstance(bucket, dict):
        raise SourceError("source_config_invalid", f"sources.{component_id} 必须是对象")
    return bucket


def missing_keys(item: Dict[str, Any], cfg: Dict[str, Any]) -> List[str]:
    return [key for key in item.get("required_keys") or [] if not str(cfg.get(key) or "").strip()]


def _expand(template: str, cfg: Dict[str, Any]) -> str:
    out = template
    for key, value in cfg.items():
        if isinstance(value, (str, int, float)):
            out = out.replace("${" + key + "}", str(value))
    return out


def _tcp_probe(target: str, timeout: float = 3.0) -> Dict[str, Any]:
    text = target.replace("tcp://", "")
    host, _, port = text.rpartition(":")
    if not host or not port.isdigit():
        return {"ok": False, "kind": "tcp", "target": target, "reason": "地址不是 host:port"}
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return {"ok": True, "kind": "tcp", "target": target}
    except OSError as exc:
        return {"ok": False, "kind": "tcp", "target": target, "reason": str(exc)}


def _http_probe(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - 只探自己配的地址
            return {"ok": 200 <= int(response.status) < 400, "kind": "http", "target": url, "status": int(response.status)}
    except Exception as exc:  # noqa: BLE001 - 探活失败的原因原样抄给用户
        return {"ok": False, "kind": "http", "target": url, "reason": str(exc)}


def probe(root: Path, component_id: str, runner: Optional[Callable[[Sequence[str]], Any]] = None) -> Dict[str, Any]:
    """组件就绪探测：只用注册表声明的方式，探不通就报缺口，不猜。"""
    item = component(component_id)
    if item is None:
        raise SourceError("source_unregistered", f"组件 {component_id} 不在注册表里", component=component_id)
    cfg = source_config(root, component_id)
    missing = missing_keys(item, cfg)
    if missing:
        raise SourceError(
            "source_config_missing",
            f"{component_id} 缺少连接键：{', '.join(missing)}（写进 .kb/config.json 的 sources.{component_id}）",
            component=component_id,
            missing=missing,
        )
    spec = item.get("probe") or {}
    if "tcp" in spec:
        result = _tcp_probe(_expand(str(spec["tcp"]), cfg))
    elif "http" in spec:
        result = _http_probe(_expand(str(spec["http"]), cfg))
    elif "cmd" in spec:
        argv = [_expand(str(part), cfg) for part in spec["cmd"]]
        proc = _runner_for(cfg, runner)(argv)
        result = {"ok": int(getattr(proc, "returncode", 1)) == 0, "kind": "cmd", "target": " ".join(argv),
                  "stdout": (getattr(proc, "stdout", "") or "").strip()[:200]}
    else:
        raise SourceError("source_probe_unknown", f"{component_id} 没有声明探测方式", component=component_id)
    result.update({"component": component_id, "display": item.get("display"), "tier": item.get("tier")})
    return result


def _runner_for(
    cfg: Dict[str, Any], runner: Optional[Callable[..., Any]] = None
) -> Callable[..., Any]:
    """返回执行器。签名 ``run(cmd, input_text=None)``。

    ``input_text`` 走 stdin，不是塞进命令行：SQL 里有反引号、括号、引号时，
    经 ``wsl.exe → bash -lc`` 传递会因为引号在这一层被吃掉而让 bash 把反引号
    当成命令替换（第一次对 StarRocks 真跑时就这么把 ``SHOW CREATE TABLE`` 打成了
    ``SHOW CREATE TABLE .``）。把语句从 stdin 喂给客户端，这条路上没有任何 shell 解析。
    """
    if runner is not None:
        return runner
    prefix = [str(part) for part in (cfg.get("runner") or [])]
    timeout = int(cfg.get("timeout") or 120)

    def _run(cmd: Sequence[str], input_text: Optional[str] = None) -> Any:
        if prefix:
            argv = prefix + [" ".join(shlex.quote(str(part)) for part in cmd)]
        else:
            argv = [str(part) for part in cmd]
        # 必须显式指定 utf-8：组件元数据里有中文注释，Windows 默认按 GBK 解码会在
        # subprocess 的读取线程里抛 UnicodeDecodeError，输出直接变成空的——
        # 第一次对 StarRocks 真跑时就这么把字段表和 DDL 采成了空（2026-10-07 实测）。
        return subprocess.run(
            argv,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    return _run


def _stdout(proc: Any, what: str) -> str:
    code = int(getattr(proc, "returncode", 1))
    if code != 0:
        detail = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()[:300]
        raise SourceError("source_collect_failed", f"{what} 失败（rc={code}）：{detail}")
    return getattr(proc, "stdout", "") or ""


# --------------------------------------------------------------------------------------
# 采集器：Kafka
# --------------------------------------------------------------------------------------


def _parse_kafka_topics(text: str) -> Dict[str, Dict[str, Any]]:
    """解析 ``kafka-topics.sh --describe`` 的两种行：主题头行与分区行。"""
    topics: Dict[str, Dict[str, Any]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        partition = re.search(r"\bPartition:\s*(\d+)", line)
        name = re.search(r"\bTopic:\s*(\S+)", line)
        if not name:
            continue
        topic = name.group(1)
        entry = topics.setdefault(topic, {"partitions": [], "configs": {}})
        if partition:
            entry["partitions"].append(
                {
                    "partition": int(partition.group(1)),
                    "leader": _group(line, r"\bLeader:\s*(\S+)"),
                    "isr": _group(line, r"\bIsr:\s*(\S+)"),
                }
            )
            continue
        entry["partition_count"] = _int_or_none(_group(line, r"\bPartitionCount:\s*(\d+)"))
        entry["replication_factor"] = _int_or_none(_group(line, r"\bReplicationFactor:\s*(\d+)"))
        entry["topic_id"] = _group(line, r"\bTopicId:\s*(\S+)")
        inline = _group(line, r"\bConfigs:\s*(.*)$")
        if inline:
            for chunk in inline.split(","):
                if "=" in chunk:
                    key, value = chunk.split("=", 1)
                    entry["configs"][key.strip()] = value.strip()
    return topics


def _parse_kafka_configs(text: str) -> Dict[str, Dict[str, str]]:
    """解析 ``kafka-configs.sh --describe``：每个主题一段 ``key=value sensitive=...``。"""
    out: Dict[str, Dict[str, str]] = {}
    current: Optional[str] = None
    for line in text.splitlines():
        header = re.search(r"Dynamic configs for topic (\S+) are", line)
        if header:
            current = header.group(1)
            out.setdefault(current, {})
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped or "=" not in stripped:
            continue
        key, rest = stripped.split("=", 1)
        value = re.split(r"\s+sensitive=", rest, maxsplit=1)[0].strip()
        out[current][key.strip()] = value
    return out


def _collect_kafka(item: Dict[str, Any], cfg: Dict[str, Any], run: Callable[[Sequence[str]], Any]) -> List[Dict[str, Any]]:
    bin_dir = str(cfg["bin"]).rstrip("/")
    servers = str(cfg["bootstrap_servers"])
    topics_text = _stdout(run([f"{bin_dir}/kafka-topics.sh", "--bootstrap-server", servers, "--describe"]), "kafka-topics --describe")
    topics = _parse_kafka_topics(topics_text)
    if not topics:
        raise SourceError("source_collect_empty", f"{item['id']} 没读到任何主题（topics 为空不算采集成功）")
    extra: Dict[str, Dict[str, str]] = {}
    configs_proc = run([f"{bin_dir}/kafka-configs.sh", "--bootstrap-server", servers, "--entity-type", "topics", "--describe"])
    if int(getattr(configs_proc, "returncode", 1)) == 0:
        extra = _parse_kafka_configs(getattr(configs_proc, "stdout", "") or "")

    entries: List[Dict[str, Any]] = []
    for topic, info in sorted(topics.items()):
        row = _empty_row(item, schema="kafka", name=topic)
        parts = info.get("partition_count") or len(info.get("partitions") or [])
        rf = info.get("replication_factor")
        merged = dict(info.get("configs") or {})
        merged.update(extra.get(topic) or {})
        retention_ms = _int_or_none(merged.get("retention.ms"))
        row["BASIC_INFO"] = {
            "domain": "stream",
            "layer": "log",
            "frequency": "streaming",
            "owner": "unknown",
            "partitions": parts,
            "replication_factor": rf,
            "comment": f"Kafka 主题（{parts} 分区" + (f" / 副本 {rf}" if rf else "") + "；属主在平台目录里，broker 内没有）",
        }
        quality: List[Dict[str, Any]] = []
        if retention_ms:
            quality.append({"rule": "retention_ms", "value": retention_ms})
        if merged.get("cleanup.policy"):
            quality.append({"rule": "cleanup_policy", "value": merged["cleanup.policy"]})
        if _int_or_none(merged.get("min.insync.replicas")):
            quality.append({"rule": "min_insync_replicas", "value": _int_or_none(merged["min.insync.replicas"])})
        row["QUALITY_RULE"] = quality
        row["PARTITION_INFO"] = {
            "partition_column": "<消息 key 的哈希>",
            "type": "key-hash",
            "partitions": parts,
            "replication_factor": rf,
            "retention_ms": retention_ms,
            "retention_days": round(retention_ms / 86400000, 1) if retention_ms else None,
            "leaders": [p.get("leader") for p in info.get("partitions") or []],
        }
        row["_component"] = item["id"]
        entries.append(row)
    return entries


# --------------------------------------------------------------------------------------
# 采集器：走 MySQL 协议的服务层（Doris / StarRocks）
# --------------------------------------------------------------------------------------

DEFAULT_SYSTEM_SCHEMAS = (
    "information_schema",
    "mysql",
    "sys",
    "__internal_schema",
    "performance_schema",
    "_statistics_",  # StarRocks 的内部统计库——真跑时混进过业务表列表（2026-10-07 实测）
)


def system_schema_filter(item: Dict[str, Any]) -> str:
    """内部库过滤名单：默认一份，组件可在注册表里覆盖（各家内部库并不相同）。"""
    names = item.get("system_schemas") or list(DEFAULT_SYSTEM_SCHEMAS)
    return "(" + ",".join(f"'{str(name)}'" for name in names) + ")"


def _mysql_argv(cfg: Dict[str, Any]) -> List[str]:
    """客户端参数。SQL 一律走 stdin（见 ``_runner_for`` 里记的原因）。"""
    argv = [str(cfg["bin"]), "-h", str(cfg["host"]), "-P", str(cfg["port"]), "-u", str(cfg.get("user") or "root")]
    if str(cfg.get("password") or ""):
        argv.append(f"-p{cfg['password']}")
    return argv + ["--batch", "--raw", "-N"]


def _rows(text: str) -> List[List[str]]:
    return [line.split("\t") for line in text.splitlines() if line.strip()]


def _collect_mysql_sql(item: Dict[str, Any], cfg: Dict[str, Any], run: Callable[[Sequence[str]], Any]) -> List[Dict[str, Any]]:
    def q(sql: str) -> Any:
        return run(_mysql_argv(cfg), input_text=sql)

    skip = system_schema_filter(item)
    tables_sql = (
        "SELECT TABLE_SCHEMA, TABLE_NAME, IFNULL(TABLE_COMMENT,''), IFNULL(TABLE_ROWS,0) "
        f"FROM information_schema.TABLES WHERE TABLE_SCHEMA NOT IN {skip} "
        "ORDER BY TABLE_SCHEMA, TABLE_NAME"
    )
    cols_sql = (
        "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, COLUMN_KEY, IFNULL(COLUMN_COMMENT,'') "
        f"FROM information_schema.COLUMNS WHERE TABLE_SCHEMA NOT IN {skip} "
        "ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"
    )
    parts_sql = (
        "SELECT TABLE_SCHEMA, TABLE_NAME, IFNULL(PARTITION_NAME,''), IFNULL(PARTITION_EXPRESSION,''), "
        f"IFNULL(PARTITION_DESCRIPTION,'') FROM information_schema.PARTITIONS WHERE TABLE_SCHEMA NOT IN {skip} "
        "ORDER BY TABLE_SCHEMA, TABLE_NAME, PARTITION_ORDINAL_POSITION"
    )
    raw_tables = _rows(_stdout(q(tables_sql), "information_schema.TABLES"))
    if not raw_tables:
        raise SourceError("source_collect_empty", f"{item['id']} 没读到任何表（空库不算采集成功）")
    columns: Dict[str, List[Dict[str, Any]]] = {}
    for schema, table, column, dtype, key, comment in (_ensure(r, 6) for r in _rows(_stdout(q(cols_sql), "information_schema.COLUMNS"))):
        columns.setdefault(f"{schema}.{table}", []).append(
            {"column": column, "data_type": dtype, "is_primary_key": key.upper() == "PRI", "comment": comment}
        )
    partitions: Dict[str, List[List[str]]] = {}
    partition_error: Optional[str] = None
    proc = q(parts_sql)
    if int(getattr(proc, "returncode", 1)) == 0:
        for schema, table, pname, pexpr, pdesc in (_ensure(r, 5) for r in _rows(getattr(proc, "stdout", "") or "")):
            partitions.setdefault(f"{schema}.{table}", []).append([pname, pexpr, pdesc])
    else:
        partition_error = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()[:200]

    with_ddl = bool(cfg.get("with_ddl", True))
    max_ddl = int(cfg.get("max_ddl_tables") or 50)
    entries: List[Dict[str, Any]] = []
    for schema, table, comment, row_count in (_ensure(r, 4) for r in raw_tables):
        key = f"{schema}.{table}"
        row = _empty_row(item, schema=schema, name=table)
        row["BASIC_INFO"] = {
            "domain": "realtime-serving",
            "layer": "serving",
            "frequency": "continuous",
            "owner": "unknown",
            "row_count": _int_or_none(row_count) or 0,
            "comment": comment or f"{item['display']} 表",
        }
        row["COLUMN_BASIC_INFO"] = columns.get(key, [])
        if not row["COLUMN_BASIC_INFO"]:
            row.setdefault(COLLECT_FAILED, {})["COLUMN_BASIC_INFO"] = "information_schema.COLUMNS 里没有这张表的字段行"
        if partition_error:
            row.setdefault(COLLECT_FAILED, {})["PARTITION_INFO"] = f"information_schema.PARTITIONS 查询失败：{partition_error}"
        elif partitions.get(key):
            first = partitions[key][0]
            row["PARTITION_INFO"] = {
                "partition_column": first[1] or "见 DDL",
                "type": "range" if first[2] else "unknown",
                "partition_count": len(partitions[key]),
                "sample": first[2][:80],
            }
        if with_ddl and len(entries) < max_ddl:
            ddl_proc = q(f"SHOW CREATE TABLE `{schema}`.`{table}`")
            if int(getattr(ddl_proc, "returncode", 1)) == 0:
                row["DDL_SQL"] = _parse_ddl(getattr(ddl_proc, "stdout", "") or "")
            else:
                row.setdefault(COLLECT_FAILED, {})["DDL_SQL"] = "SHOW CREATE TABLE 失败"
        else:
            reason = (
                f"表数超过 max_ddl_tables={max_ddl}，本期没取 DDL"
                if with_ddl
                else "配置 with_ddl=false，本期没取 DDL"
            )
            row.setdefault(COLLECT_FAILED, {})["DDL_SQL"] = reason
        row["_component"] = item["id"]
        entries.append(row)
    return entries


# --------------------------------------------------------------------------------------
# 行构造与采集入口
# --------------------------------------------------------------------------------------


# --------------------------------------------------------------------------------------
# 采集器：ClickHouse（HTTP/原生协议的那个服务层）
# --------------------------------------------------------------------------------------


CLICKHOUSE_SYSTEM_SCHEMAS = ("system", "INFORMATION_SCHEMA", "information_schema")


def _clickhouse_argv(cfg: Dict[str, Any]) -> List[str]:
    """客户端参数。SQL 一律走 stdin（同 mysql 采集器的那条纪律）。"""
    argv = [
        str(cfg["bin"]),
        "exec",
        "-i",
        str(cfg["container"]),
        "clickhouse-client",
        "--format",
        "TabSeparated",
    ]
    if str(cfg.get("user") or ""):
        argv += ["--user", str(cfg["user"])]
    if str(cfg.get("password") or ""):
        argv += ["--password", str(cfg["password"])]
    return argv


def _parse_ddl_clickhouse(stdout: str) -> str:
    """``SHOW CREATE TABLE`` 在 ClickHouse 里只有一列（statement），且 TabSeparated 会把
    语句里的换行转义成 ``\\n``、单引号转义成 ``\\'``。取首行、按需取最后一列、把转义还原
    （不还原的话，生成的文档里会出现 ``COMMENT \\'窗口起点\\'`` 这种带反斜杠的怪样子）。"""
    text = (stdout or "").strip("\n")
    if not text:
        return ""
    head = text.split("\n")[0].split("\t")
    statement = head[-1] if head else ""
    for escaped, real in (("\\n", "\n"), ("\\t", "\t"), ("\\'", "'"), ("\\\\", "\\")):
        statement = statement.replace(escaped, real)
    return statement


def _collect_clickhouse(item: Dict[str, Any], cfg: Dict[str, Any], run: Callable[[Sequence[str]], Any]) -> List[Dict[str, Any]]:
    def q(sql: str) -> Any:
        return run(_clickhouse_argv(cfg), input_text=sql)

    skip = system_schema_filter(item)
    # system.columns 的列名里有保留字 table，用反引号——SQL 走 stdin，反引号不会经过任何 shell。
    tables_sql = (
        "SELECT database, name, ifNull(comment, ''), ifNull(total_rows, 0) "
        f"FROM system.tables WHERE database NOT IN {skip} ORDER BY database, name"
    )
    cols_sql = (
        "SELECT database, `table`, name, type, if(is_in_primary_key, 1, 0), ifNull(comment, '') "
        f"FROM system.columns WHERE database NOT IN {skip} ORDER BY database, `table`, position"
    )
    parts_sql = (
        "SELECT database, `table`, ifNull(partition, ''), ifNull(partition_id, '') "
        f"FROM system.parts WHERE active AND database NOT IN {skip} ORDER BY database, `table`, partition"
    )
    raw_tables = _rows(_stdout(q(tables_sql), "system.tables"))
    if not raw_tables:
        raise SourceError("source_collect_empty", f"{item['id']} 没读到任何表（空实例不算采集成功）")

    columns: Dict[str, List[Dict[str, Any]]] = {}
    for database, table, column, dtype, is_pk, comment in (
        _ensure(r, 6) for r in _rows(_stdout(q(cols_sql), "system.columns"))
    ):
        columns.setdefault(f"{database}.{table}", []).append(
            {
                "column": column,
                "data_type": dtype,
                "is_primary_key": str(is_pk).strip() == "1",
                "comment": comment,
            }
        )

    partitions: Dict[str, List[List[str]]] = {}
    partition_error: Optional[str] = None
    proc = q(parts_sql)
    if int(getattr(proc, "returncode", 1)) == 0:
        for database, table, part, part_id in (_ensure(r, 4) for r in _rows(getattr(proc, "stdout", "") or "")):
            partitions.setdefault(f"{database}.{table}", []).append([part, part_id])
    else:
        partition_error = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()[:200]

    with_ddl = bool(cfg.get("with_ddl", True))
    max_ddl = int(cfg.get("max_ddl_tables") or 50)
    entries: List[Dict[str, Any]] = []
    for database, table, comment, total_rows in (_ensure(r, 4) for r in raw_tables):
        key = f"{database}.{table}"
        row = _empty_row(item, schema=database, name=table)
        row["BASIC_INFO"] = {
            "domain": "realtime-serving",
            "layer": "serving",
            "frequency": "continuous",
            "owner": "unknown",
            "row_count": _int_or_none(total_rows) or 0,
            "comment": comment or f"{item['display']} 表",
        }
        row["COLUMN_BASIC_INFO"] = columns.get(key, [])
        if not row["COLUMN_BASIC_INFO"]:
            row.setdefault(COLLECT_FAILED, {})["COLUMN_BASIC_INFO"] = "system.columns 里没有这张表的字段行"
        if partition_error:
            row.setdefault(COLLECT_FAILED, {})["PARTITION_INFO"] = f"system.parts 查询失败：{partition_error}"
        elif partitions.get(key):
            row["PARTITION_INFO"] = {
                "partition_column": "partition",
                "type": "partition",
                "partition_count": len(partitions[key]),
                "sample": partitions[key][0][0][:80],
            }
        if with_ddl and len(entries) < max_ddl:
            ddl_proc = q(f"SHOW CREATE TABLE `{database}`.`{table}`")
            if int(getattr(ddl_proc, "returncode", 1)) == 0:
                row["DDL_SQL"] = _parse_ddl_clickhouse(getattr(ddl_proc, "stdout", "") or "")
            else:
                row.setdefault(COLLECT_FAILED, {})["DDL_SQL"] = "SHOW CREATE TABLE 失败"
        else:
            row.setdefault(COLLECT_FAILED, {})["DDL_SQL"] = (
                f"表数超过 max_ddl_tables={max_ddl}，本期没取 DDL"
                if with_ddl
                else "配置 with_ddl=false，本期没取 DDL"
            )
        row["_component"] = item["id"]
        entries.append(row)
    return entries


COLLECTORS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any], Callable[[Sequence[str]], Any]], List[Dict[str, Any]]]] = {
    "kafka_cli": _collect_kafka,
    "mysql_sql": _collect_mysql_sql,
    "clickhouse_sql": _collect_clickhouse,
}


def _group(text: str, pattern: str, default: Optional[str] = None) -> Optional[str]:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else default


def _parse_ddl(stdout: str) -> str:
    """``SHOW CREATE TABLE`` 的输出：第一行是 ``表名<TAB>DDL 首行``，其余行是 DDL 的后续行。

    不能用 ``_rows`` 逐行 split 后只取首行——``--raw`` 下 DDL 是真换行，
    只取首行会把建表语句截断成 ``CREATE TABLE `x` (``（2026-10-07 真跑时踩到）。
    """
    text = (stdout or "").rstrip("\n")
    if not text:
        return ""
    lines = text.split("\n")
    head = lines[0].split("\t")
    if len(head) < 2:
        return ""
    return head[1] + "".join("\n" + line for line in lines[1:])


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _ensure(row: List[str], width: int) -> List[str]:
    return (row + [""] * width)[:width]


def _empty_row(item: Dict[str, Any], schema: str, name: str) -> Dict[str, Any]:
    """按 6 类契约建空行：类别值类型固定，不适用/采失败的都记在进行级标记里。"""
    row: Dict[str, Any] = {"schema": schema, "name": name, "table_id": name, COLLECT_FAILED: {}, NOT_APPLICABLE: {}}
    coverage = item.get("coverage") or {}
    reasons = item.get("not_applicable_reasons") or {}
    for category in contract_categories():
        if coverage.get(category) == "not_applicable":
            row[NOT_APPLICABLE][category] = reasons.get(category, "该组件没有这一类知识")
        row[category] = _empty_value(category)
    return row


def _empty_value(category: str) -> Any:
    return {"COLUMN_BASIC_INFO": [], "QUALITY_RULE": [], "DDL_SQL": ""}.get(category, {})


def collect(root: Path, component_id: str, runner: Optional[Callable[[Sequence[str]], Any]] = None) -> Dict[str, Any]:
    """对某个组件做一次真实采集，返回契约行（不落盘；落盘由 snapshot 负责）。"""
    item = component(component_id)
    if item is None:
        raise SourceError("source_unregistered", f"组件 {component_id} 不在注册表里", component=component_id)
    collector_name = item.get("collector")
    if not collector_name:
        raise SourceError(
            "collector_not_implemented",
            f"{component_id} 只登记了角色与连接形状（tier {item.get('tier')}），还没有采集器——不假装支持",
            component=component_id,
        )
    collector = COLLECTORS.get(collector_name)
    if collector is None:
        raise SourceError("collector_not_implemented", f"引擎里没有采集器实现：{collector_name}", component=component_id)
    cfg = source_config(root, component_id)
    missing = missing_keys(item, cfg)
    if missing:
        raise SourceError(
            "source_config_missing",
            f"{component_id} 缺少连接键：{', '.join(missing)}（写进 .kb/config.json 的 sources.{component_id}）",
            component=component_id,
            missing=missing,
        )
    run = _runner_for(cfg, runner)
    entries = collector(item, cfg, run)
    return {
        "component": component_id,
        "display": item.get("display"),
        "role": item.get("role"),
        "tier": item.get("tier"),
        "entries": entries,
        "source": f"{SOURCE_PREFIX}{component_id}",
    }


def describe(component_id: str) -> Dict[str, Any]:
    item = component(component_id)
    if item is None:
        raise SourceError("source_unregistered", f"组件 {component_id} 不在注册表里", component=component_id)
    return {
        "id": item.get("id"),
        "display": item.get("display"),
        "role": item.get("role"),
        "collector": item.get("collector"),
        "tier": item.get("tier"),
        "required_keys": item.get("required_keys"),
        "coverage": item.get("coverage"),
        "verified": item.get("verified"),
        "supported": bool(item.get("collector")),
    }


def dump_registry() -> str:
    return json.dumps(load_registry(), ensure_ascii=False, indent=2)
