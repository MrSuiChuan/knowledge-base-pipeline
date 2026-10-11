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
"""Unit tests: 实时组件知识源（注册表 / 采集器 / 来源门 / 探活 / CLI / 端到端）。

全部用桩，不依赖本机装了组件；唯一的真实 socket 是探活用例里临时开的本机监听端口。
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT_REPO = Path(__file__).resolve().parent.parent
ENGINE = ROOT_REPO / "engine"
sys.path.insert(0, str(ENGINE))

from core import audit, context, render, skeleton, snapshot, sources  # noqa: E402

KAFKA_TOPICS = (
    "Topic: rtd_smoke\tTopicId: abc123\tPartitionCount: 3\tReplicationFactor: 1\tConfigs: segment.bytes=1073741824\n"
    "\tTopic: rtd_smoke\tPartition: 0\tLeader: 1\tReplicas: 1\tIsr: 1\tElr: \tLastKnownElr: \n"
    "\tTopic: rtd_smoke\tPartition: 1\tLeader: 2\tReplicas: 1\tIsr: 1\tElr: \tLastKnownElr: \n"
    "\tTopic: rtd_smoke\tPartition: 2\tLeader: 3\tReplicas: 1\tIsr: 1\tElr: \tLastKnownElr: \n"
    "Topic: rtd_orders\tTopicId: def456\tPartitionCount: 1\tReplicationFactor: 1\tConfigs: \n"
    "\tTopic: rtd_orders\tPartition: 0\tLeader: 1\tReplicas: 1\tIsr: 1\tElr: \tLastKnownElr: \n"
)

KAFKA_CONFIGS = (
    "Dynamic configs for topic rtd_smoke are:\n"
    "  retention.ms=604800000 sensitive=false synonyms={}\n"
    "  cleanup.policy=delete sensitive=false synonyms={}\n"
    "  min.insync.replicas=2 sensitive=false synonyms={}\n"
)


class _Proc:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def kafka_runner(topics: str = KAFKA_TOPICS, configs: str = KAFKA_CONFIGS):
    """桩：按命令行里出现的脚本名返回预置输出，不真起 Kafka。"""

    def _run(cmd):
        text = " ".join(str(part) for part in cmd)
        if "kafka-topics.sh" in text:
            return _Proc(topics)
        if "kafka-configs.sh" in text:
            return _Proc(configs)
        return _Proc("", 1, f"unexpected command: {text}")

    return _run


class SourcesBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        context.ensure_app_dir(self.root, mode="mock", domain="user")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def configure(self, bucket: dict) -> None:
        config = context.load_config(self.root)
        config["sources"] = bucket
        context.write_json(context.config_path(self.root), config)


def run_engine(root: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ENGINE / "kbp.py"), "--root", str(root), *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class RegistryTests(SourcesBase):
    def test_registry_is_self_consistent(self) -> None:
        self.assertEqual([], sources.registry_errors())

    def test_contract_has_the_six_documented_categories(self) -> None:
        self.assertEqual(
            [
                "BASIC_INFO",
                "COLUMN_BASIC_INFO",
                "DDL_SQL",
                "SCHEDULE_TASK",
                "QUALITY_RULE",
                "PARTITION_INFO",
            ],
            sources.contract_categories(),
        )

    def test_unregistered_component_is_refused(self) -> None:
        for call in (
            lambda: sources.describe("oss_nope"),
            lambda: sources.probe(self.root, "oss_nope"),
            lambda: sources.collect(self.root, "oss_nope"),
        ):
            with self.assertRaises(sources.SourceError) as ctx:
                call()
            self.assertEqual("source_unregistered", ctx.exception.gate)

    def test_registered_without_collector_refuses_loudly(self) -> None:
        """tier 3 的组件只登记了形状：要说"没有采集器"，不能返回空结果冒充采到了。"""
        with self.assertRaises(sources.SourceError) as ctx:
            sources.collect(self.root, "oss_pulsar")
        self.assertEqual("collector_not_implemented", ctx.exception.gate)

    def test_missing_connection_keys_are_named(self) -> None:
        self.configure({})
        with self.assertRaises(sources.SourceError) as ctx:
            sources.collect(self.root, "oss_kafka")
        self.assertEqual("source_config_missing", ctx.exception.gate)
        self.assertEqual(["bin", "bootstrap_servers"], ctx.exception.extra["missing"])


class KafkaCollectorTests(SourcesBase):
    def setUp(self) -> None:
        super().setUp()
        self.configure({"oss_kafka": {"bin": "/opt/kafka/bin", "bootstrap_servers": "127.0.0.1:9092"}})

    def test_topics_map_to_the_contract(self) -> None:
        result = sources.collect(self.root, "oss_kafka", runner=kafka_runner())
        rows = {row["table_id"]: row for row in result["entries"]}
        self.assertEqual({"rtd_smoke", "rtd_orders"}, set(rows))
        smoke = rows["rtd_smoke"]
        self.assertEqual("oss:oss_kafka", result["source"])
        self.assertEqual(3, smoke["BASIC_INFO"]["partitions"])
        self.assertEqual(1, smoke["BASIC_INFO"]["replication_factor"])
        rules = {rule["rule"]: rule["value"] for rule in smoke["QUALITY_RULE"]}
        self.assertEqual(604800000, rules["retention_ms"])
        self.assertEqual("delete", rules["cleanup_policy"])
        self.assertEqual(2, rules["min_insync_replicas"])
        self.assertEqual(7.0, smoke["PARTITION_INFO"]["retention_days"])
        self.assertEqual(["1", "2", "3"], smoke["PARTITION_INFO"]["leaders"])

    def test_not_applicable_is_stated_not_faked(self) -> None:
        rows = {row["table_id"]: row for row in sources.collect(self.root, "oss_kafka", runner=kafka_runner())["entries"]}
        smoke = rows["rtd_smoke"]
        self.assertEqual(
            {"COLUMN_BASIC_INFO", "DDL_SQL", "SCHEDULE_TASK"},
            set(smoke[sources.NOT_APPLICABLE]),
        )
        for category in ("COLUMN_BASIC_INFO", "DDL_SQL", "SCHEDULE_TASK"):
            self.assertTrue(smoke[sources.NOT_APPLICABLE][category].strip(), category)
        self.assertEqual([], smoke["COLUMN_BASIC_INFO"])
        self.assertEqual("", smoke["DDL_SQL"])
        self.assertEqual({}, smoke[sources.COLLECT_FAILED])

    def test_empty_topic_list_is_not_a_success(self) -> None:
        with self.assertRaises(sources.SourceError) as ctx:
            sources.collect(self.root, "oss_kafka", runner=kafka_runner(topics=""))
        self.assertEqual("source_collect_empty", ctx.exception.gate)

    def test_collect_failure_carries_the_raw_reason(self) -> None:
        def broken(_cmd):
            return _Proc("", 1, "Connection refused")

        with self.assertRaises(sources.SourceError) as ctx:
            sources.collect(self.root, "oss_kafka", runner=broken)
        self.assertEqual("source_collect_failed", ctx.exception.gate)
        self.assertIn("Connection refused", ctx.exception.reason)


class SourceGateTests(SourcesBase):
    def setUp(self) -> None:
        super().setUp()
        self.configure({"oss_kafka": {"bin": "/opt/kafka/bin", "bootstrap_servers": "127.0.0.1:9092"}})

    def test_snapshot_records_the_real_source(self) -> None:
        snap = snapshot.fetch_metadata(self.root, "user", source="oss:oss_kafka", runner=kafka_runner())
        self.assertEqual("oss:oss_kafka", snap["source"])
        self.assertEqual(2, len(snap["tables"]))
        row = snap["tables"][0]
        self.assertEqual("oss_kafka", row["_component"])
        self.assertIn(sources.NOT_APPLICABLE, row)
        self.assertTrue(Path(snap["_file"]).is_file())

    def test_snapshot_source_can_come_from_config(self) -> None:
        config = context.load_config(self.root)
        config["snapshot"] = {"source": "oss:oss_kafka"}
        context.write_json(context.config_path(self.root), config)
        self.assertEqual("oss:oss_kafka", snapshot.resolve_source(context.load_config(self.root)))
        snap = snapshot.fetch_metadata(self.root, "user", runner=kafka_runner())
        self.assertEqual("oss:oss_kafka", snap["source"])

    def test_unknown_source_is_blocked_without_writing_a_snapshot(self) -> None:
        with self.assertRaises(sources.SourceError) as ctx:
            snapshot.fetch_metadata(self.root, "user", source="made-up-source")
        self.assertEqual("source_unregistered", ctx.exception.gate)
        self.assertEqual([], list(context.snapshot_dir(self.root).glob("metadata-snapshot-*.json")))

    def test_mock_snapshot_does_not_disguise_itself_as_platform(self) -> None:
        snap = snapshot.fetch_metadata(self.root, "user")
        self.assertEqual("mock", snap["source"])
        self.assertEqual("mock", snapshot.latest_snapshot(self.root)["source"])


SQL_TABLES = "stream_db\torders_by_minute\t每分钟订单聚合\t120\nstream_db\tclicks_raw\t点击原始流\t960\n"
SQL_COLUMNS = (
    "stream_db\torders_by_minute\twindow_start\tDATETIME\tPRI\t窗口起点\n"
    "stream_db\torders_by_minute\torder_cnt\tBIGINT\t\t订单数\n"
    "stream_db\tclicks_raw\tevent_time\tDATETIME\t\t事件时间\n"
)
SQL_PARTITIONS = 'stream_db\torders_by_minute\tp20261007\tRANGE(k1)\t["2026-10-07", "2026-10-08"]\n'


def sql_runner(
    tables: str = SQL_TABLES,
    columns: str = SQL_COLUMNS,
    partitions: str = SQL_PARTITIONS,
    partitions_rc: int = 0,
    partitions_err: str = "",
    ddl: str = "CREATE TABLE `{table}` (`window_start` DATETIME, `order_cnt` BIGINT) ENGINE=OLAP",
    seen: list | None = None,
    sql_seen: list | None = None,
):
    """桩：按 stdin 里的 SQL 分流，覆盖 TABLES / COLUMNS / PARTITIONS / SHOW CREATE TABLE。

    SQL 走 stdin 而不是命令行——这正是防 shell 引号被吃掉的那条纪律，
    桩也必须照这个形状来，否则测不到真实调用路径。
    """

    def _run(cmd, input_text=None):
        sql = str(input_text or "")
        if seen is not None:
            seen.append(list(cmd))
        if sql_seen is not None:
            sql_seen.append(sql)
        if "information_schema.TABLES" in sql:
            return _Proc(tables)
        if "information_schema.COLUMNS" in sql:
            return _Proc(columns)
        if "information_schema.PARTITIONS" in sql:
            return _Proc(partitions, partitions_rc, partitions_err)
        if sql.startswith("SHOW CREATE TABLE"):
            table = sql.split("`")[-2]
            return _Proc(f"{table}\t{ddl.format(table=table)}")
        return _Proc("", 1, f"unexpected: {sql[:60]}")

    return _run


class MysqlCollectorTests(SourcesBase):
    """服务层采集器（Doris / StarRocks 共用）：真跑未做，逻辑先钉死。"""

    def setUp(self) -> None:
        super().setUp()
        self.configure(
            {"oss_doris": {"bin": "/usr/bin/mysql", "host": "127.0.0.1", "port": "9030", "user": "root"}}
        )

    def test_tables_columns_ddl_partitions_map_to_the_contract(self) -> None:
        entries = sources.collect(self.root, "oss_doris", runner=sql_runner())["entries"]
        rows = {row["table_id"]: row for row in entries}
        self.assertEqual({"orders_by_minute", "clicks_raw"}, set(rows))
        orders = rows["orders_by_minute"]
        self.assertEqual("stream_db", orders["schema"])
        self.assertEqual(120, orders["BASIC_INFO"]["row_count"])
        self.assertEqual("每分钟订单聚合", orders["BASIC_INFO"]["comment"])
        self.assertEqual(2, len(orders["COLUMN_BASIC_INFO"]))
        self.assertTrue(orders["COLUMN_BASIC_INFO"][0]["is_primary_key"])
        self.assertIn("CREATE TABLE `orders_by_minute`", orders["DDL_SQL"])
        self.assertEqual(1, orders["PARTITION_INFO"]["partition_count"])
        self.assertEqual("range", orders["PARTITION_INFO"]["type"])
        self.assertEqual(
            {"SCHEDULE_TASK", "QUALITY_RULE"},
            set(orders[sources.NOT_APPLICABLE]),
        )
        self.assertEqual({}, orders[sources.COLLECT_FAILED])

    def test_partition_query_failure_is_reported_not_treated_as_absent(self) -> None:
        runner = sql_runner(partitions="", partitions_rc=1, partitions_err="PARTITIONS not supported")
        orders = {r["table_id"]: r for r in sources.collect(self.root, "oss_doris", runner=runner)["entries"]}["orders_by_minute"]
        self.assertEqual({}, orders["PARTITION_INFO"])
        self.assertIn("PARTITIONS not supported", orders[sources.COLLECT_FAILED]["PARTITION_INFO"])

    def test_ddl_cap_and_switch_are_visible_in_the_row(self) -> None:
        capped = context.load_config(self.root)
        capped["sources"]["oss_doris"]["max_ddl_tables"] = 1
        context.write_json(context.config_path(self.root), capped)
        rows = {r["table_id"]: r for r in sources.collect(self.root, "oss_doris", runner=sql_runner())["entries"]}
        self.assertTrue(rows["orders_by_minute"]["DDL_SQL"])
        self.assertIn("max_ddl_tables", rows["clicks_raw"][sources.COLLECT_FAILED]["DDL_SQL"])

        off = context.load_config(self.root)
        off["sources"]["oss_doris"]["with_ddl"] = False
        context.write_json(context.config_path(self.root), off)
        rows = {r["table_id"]: r for r in sources.collect(self.root, "oss_doris", runner=sql_runner())["entries"]}
        self.assertEqual("", rows["orders_by_minute"]["DDL_SQL"])
        self.assertIn("with_ddl=false", rows["orders_by_minute"][sources.COLLECT_FAILED]["DDL_SQL"])

    def test_empty_database_is_not_a_success(self) -> None:
        with self.assertRaises(sources.SourceError) as ctx:
            sources.collect(self.root, "oss_doris", runner=sql_runner(tables=""))
        self.assertEqual("source_collect_empty", ctx.exception.gate)

    def test_multiline_ddl_is_not_truncated(self) -> None:
        """``--raw`` 下 DDL 是真换行：只取首行会把建表语句截成 ``CREATE TABLE x (``。"""
        multi = "CREATE TABLE `orders_by_minute` (\n  `window_start` DATETIME,\n  `order_cnt` BIGINT\n) ENGINE=OLAP"
        rows = {r["table_id"]: r for r in sources.collect(self.root, "oss_doris", runner=sql_runner(ddl=multi))["entries"]}
        ddl = rows["orders_by_minute"]["DDL_SQL"]
        self.assertTrue(ddl.endswith(") ENGINE=OLAP"), ddl)
        self.assertEqual(3, ddl.count("\n"))
        self.assertEqual({}, rows["orders_by_minute"][sources.COLLECT_FAILED])

    def test_password_is_passed_to_the_client_exactly_once(self) -> None:
        cfg = context.load_config(self.root)
        cfg["sources"]["oss_doris"]["password"] = "s3cret"
        context.write_json(context.config_path(self.root), cfg)
        seen: list = []
        sources.collect(self.root, "oss_doris", runner=sql_runner(seen=seen))
        argv = seen[0]
        self.assertEqual(["-ps3cret"], [token for token in argv if token.startswith("-p")])
        self.assertEqual(argv[argv.index("-u") + 1], "root")

    def test_system_schemas_are_filtered_per_component(self) -> None:
        """内部库过滤名单来自注册表：StarRocks 多一个 _statistics_（首次真跑时混进过业务表）。"""
        doris = sources.system_schema_filter(sources.component("oss_doris"))
        starrocks = sources.system_schema_filter(sources.component("oss_starrocks"))
        self.assertNotIn("_statistics_", doris)
        self.assertIn("_statistics_", starrocks)
        self.assertIn("information_schema", starrocks)

    def test_collect_sql_carries_the_component_filter(self) -> None:
        seen: list = []
        sqls: list = []
        sources.collect(self.root, "oss_doris", runner=sql_runner(seen=seen, sql_seen=sqls))
        tables_sql = sqls[0]
        self.assertIn("NOT IN", tables_sql)
        self.assertIn("'information_schema'", tables_sql)
        # SQL 不进命令行：免得 wsl.exe → bash -lc 那一层把反引号当命令替换
        self.assertNotIn("SELECT", " ".join(seen[0]))


class ProbeTests(SourcesBase):
    def setUp(self) -> None:
        super().setUp()
        self.configure({"oss_kafka": {"bin": "/opt/kafka/bin", "bootstrap_servers": "127.0.0.1:9092"}})

    def test_tcp_probe_reports_open_and_closed_ports(self) -> None:
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        try:
            opened = sources._tcp_probe(f"127.0.0.1:{port}")
        finally:
            server.close()
        self.assertTrue(opened["ok"], opened)
        self.assertFalse(sources._tcp_probe(f"127.0.0.1:{port}")["ok"])
        self.assertFalse(sources._tcp_probe("127.0.0.1:not-a-port")["ok"])

    def test_http_probe_fails_closed_on_unreachable_address(self) -> None:
        result = sources._http_probe("http://127.0.0.1:1/overview", timeout=1)
        self.assertFalse(result["ok"])
        self.assertTrue(result["reason"])

    def test_cmd_probe_asks_the_component_itself(self) -> None:
        ok = sources.probe(self.root, "oss_kafka", runner=lambda _cmd: _Proc("kb_smoke_orders\n"))
        self.assertTrue(ok["ok"], ok)
        self.assertEqual("cmd", ok["kind"])
        self.assertIn("kafka-topics.sh", ok["target"])
        bad = sources.probe(self.root, "oss_kafka", runner=lambda _cmd: _Proc("", 1, "Connection refused"))
        self.assertFalse(bad["ok"])

    def test_runner_prefix_joins_the_command_into_one_argument(self) -> None:
        cfg = {"runner": ["wsl", "-d", "Debian", "--", "bash", "-lc"]}
        with mock.patch.object(sources.subprocess, "run") as fake:
            fake.return_value = _Proc("")
            sources._runner_for(cfg)(["/opt/kafka/bin/kafka-topics.sh", "--topic", "a b"])
        argv = fake.call_args.args[0]
        self.assertEqual(["wsl", "-d", "Debian", "--", "bash", "-lc"], argv[:6])
        self.assertEqual(7, len(argv), argv)
        self.assertEqual("/opt/kafka/bin/kafka-topics.sh --topic 'a b'", argv[6])


CH_TABLES = "kb_stream\torders_by_minute\t每分钟订单聚合\t3\n"
CH_COLUMNS = (
    "kb_stream\torders_by_minute\twindow_start\tDateTime\t1\t窗口起点\n"
    "kb_stream\torders_by_minute\torder_cnt\tUInt64\t0\t订单数\n"
)
CH_PARTS = "kb_stream\torders_by_minute\t20261007\t20261007\n"
CH_DDL = (
    "CREATE TABLE kb_stream.orders_by_minute\\n(\\n    `window_start` DateTime COMMENT \\'窗口起点\\',"
    "\\n    `order_cnt` UInt64\\n)\\nENGINE = MergeTree\\nORDER BY window_start"
)


def clickhouse_runner(
    tables: str = CH_TABLES,
    columns: str = CH_COLUMNS,
    parts: str = CH_PARTS,
    parts_rc: int = 0,
    parts_err: str = "",
    ddl: str = CH_DDL,
    seen: list | None = None,
    sql_seen: list | None = None,
):
    """桩：按 stdin 里的 SQL 分流；SHOW CREATE TABLE 是单列输出。"""

    def _run(cmd, input_text=None):
        sql = str(input_text or "")
        if seen is not None:
            seen.append(list(cmd))
        if sql_seen is not None:
            sql_seen.append(sql)
        if "system.tables" in sql:
            return _Proc(tables)
        if "system.columns" in sql:
            return _Proc(columns)
        if "system.parts" in sql:
            return _Proc(parts, parts_rc, parts_err)
        if sql.startswith("SHOW CREATE TABLE"):
            return _Proc(ddl + "\n")
        return _Proc("", 1, f"unexpected: {sql[:60]}")

    return _run


class ClickHouseCollectorTests(SourcesBase):
    """ClickHouse 采集器：命令形状与契约映射都钉住，再拿真容器验一遍。"""

    def setUp(self) -> None:
        super().setUp()
        self.configure({"oss_clickhouse": {"bin": "/usr/bin/docker", "container": "kb-ch"}})

    def test_tables_columns_ddl_partitions_map_to_the_contract(self) -> None:
        entries = sources.collect(self.root, "oss_clickhouse", runner=clickhouse_runner())["entries"]
        rows = {row["table_id"]: row for row in entries}
        self.assertEqual({"orders_by_minute"}, set(rows))
        orders = rows["orders_by_minute"]
        self.assertEqual("kb_stream", orders["schema"])
        self.assertEqual(3, orders["BASIC_INFO"]["row_count"])
        self.assertEqual("每分钟订单聚合", orders["BASIC_INFO"]["comment"])
        self.assertEqual(2, len(orders["COLUMN_BASIC_INFO"]))
        self.assertTrue(orders["COLUMN_BASIC_INFO"][0]["is_primary_key"])
        self.assertIn("ENGINE = MergeTree", orders["DDL_SQL"])
        self.assertEqual(1, orders["PARTITION_INFO"]["partition_count"])
        self.assertEqual({"SCHEDULE_TASK", "QUALITY_RULE"}, set(orders[sources.NOT_APPLICABLE]))
        self.assertEqual({}, orders[sources.COLLECT_FAILED])

    def test_escaped_newlines_in_ddl_are_unescaped(self) -> None:
        """TabSeparated 把语句里的换行转义成 \\n；不还原的话建表语句会挤成一行。"""
        orders = {r["table_id"]: r for r in sources.collect(self.root, "oss_clickhouse", runner=clickhouse_runner())["entries"]}[
            "orders_by_minute"
        ]
        self.assertEqual(6, orders["DDL_SQL"].count("\n"))
        self.assertNotIn("\\n", orders["DDL_SQL"])
        # TabSeparated 还会把单引号转义成 \' —— 不还原，文档里就是 COMMENT \'窗口起点\'
        self.assertNotIn("\\'", orders["DDL_SQL"])
        self.assertIn("COMMENT '窗口起点'", orders["DDL_SQL"])

    def test_partition_query_failure_is_reported_not_treated_as_absent(self) -> None:
        runner = clickhouse_runner(parts="", parts_rc=1, parts_err="system.parts denied")
        orders = {
            r["table_id"]: r
            for r in sources.collect(self.root, "oss_clickhouse", runner=runner)["entries"]
        }["orders_by_minute"]
        self.assertEqual({}, orders["PARTITION_INFO"])
        self.assertIn("system.parts denied", orders[sources.COLLECT_FAILED]["PARTITION_INFO"])

    def test_client_goes_through_docker_exec_and_sql_stays_on_stdin(self) -> None:
        seen: list = []
        sqls: list = []
        sources.collect(self.root, "oss_clickhouse", runner=clickhouse_runner(seen=seen, sql_seen=sqls))
        self.assertEqual(
            ["/usr/bin/docker", "exec", "-i", "kb-ch", "clickhouse-client", "--format", "TabSeparated"],
            seen[0],
        )
        self.assertIn("system.tables", sqls[0])
        self.assertNotIn("SELECT", " ".join(seen[0]))

    def test_empty_instance_is_not_a_success(self) -> None:
        with self.assertRaises(sources.SourceError) as ctx:
            sources.collect(self.root, "oss_clickhouse", runner=clickhouse_runner(tables=""))
        self.assertEqual("source_collect_empty", ctx.exception.gate)


class SourcesCliTests(unittest.TestCase):
    """命令层：退出码与门控键是给使用者看的接口，也要钉住。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        setup = run_engine(self.root, "setup", "--mode", "mock", "--domain", "stream")
        self.assertEqual(0, setup.returncode, setup.stdout + setup.stderr)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_sources_list_shows_a_clean_registry(self) -> None:
        proc = run_engine(self.root, "sources", "list")
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual([], payload["problems"])
        ids = {item["id"] for item in payload["components"]}
        self.assertIn("oss_kafka", ids)
        self.assertIn("oss_clickhouse", ids)

    def test_unimplemented_collector_exits_with_its_gate(self) -> None:
        proc = run_engine(self.root, "sources", "collect", "--component", "oss_flink")
        self.assertEqual(3, proc.returncode, proc.stdout)
        self.assertEqual("collector_not_implemented", json.loads(proc.stdout)["gate"])

    def test_unregistered_source_exits_with_its_gate_and_writes_nothing(self) -> None:
        proc = run_engine(self.root, "snapshot", "fetch", "--domain", "stream", "--source", "oss:nope")
        self.assertEqual(3, proc.returncode, proc.stdout)
        self.assertEqual("source_unregistered", json.loads(proc.stdout)["gate"])
        self.assertEqual([], list((self.root / ".kb" / "runtime" / "snapshots").glob("*.json")))

    def test_missing_connection_keys_exit_with_the_key_names(self) -> None:
        proc = run_engine(self.root, "sources", "check", "--component", "oss_kafka")
        self.assertEqual(3, proc.returncode, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual("source_config_missing", payload["gate"])
        self.assertEqual(["bin", "bootstrap_servers"], payload["missing"])


class ComponentSourcedPipelineTests(SourcesBase):
    """端到端：组件来源的快照能不能带着空类别与 NOT_APPLICABLE 走完后半程。"""

    def setUp(self) -> None:
        super().setUp()
        self.configure({"oss_kafka": {"bin": "/opt/kafka/bin", "bootstrap_servers": "127.0.0.1:9092"}})

    def _stream_skeleton(self) -> dict:
        return {
            "domain": "stream",
            "steps_completed": [1, 2, 3, 4, 5],
            "business_panorama": "订单流 → 每分钟聚合 → 实时看板",
            "scope": "实时订单域",
            "entities": [{"name": "order", "desc": "订单事件"}],
            "processes": [{"name": "聚合", "desc": "按分钟滚动聚合"}],
            "scenarios": [
                {
                    "name": "订单量监控",
                    "anchor_table": "rtd_smoke",
                    "scope_tables": ["rtd_smoke"],
                    "goal": "每分钟订单数",
                }
            ],
            "rules": [{"concept": "订单量", "definition": "一分钟窗口内的事件条数", "scope": "stream"}],
            "table_notes": [
                {
                    "table_id": "rtd_smoke",
                    "business_context": "订单事件流，上游是交易库 CDC",
                    "upstream_calibers": ["概念「订单量」= 一分钟窗口内的事件条数"],
                    "joins": [],
                    "faq": [{"q": "为什么没有字段表", "a": "消息组件没有 schema，字段在上游生产者"}],
                    "keywords": ["订单", "实时"],
                }
            ],
            "goals": [{"goal": "订单实时监控", "metrics": ["order_cnt"], "tables": ["rtd_smoke"]}],
            "keywords": {"订单": ["rtd_smoke"]},
        }

    def test_oss_snapshot_drives_the_rest_of_the_pipeline(self) -> None:
        snap = snapshot.fetch_metadata(self.root, "stream", source="oss:oss_kafka", runner=kafka_runner())
        self.assertEqual("oss:oss_kafka", snap["source"])
        skeleton.save(self.root, "stream", self._stream_skeleton())

        context.ensure_dir(context.tables_dir(self.root, "stream"))
        notes = {n["table_id"]: n for n in self._stream_skeleton()["table_notes"]}
        for table in snap["tables"]:
            table_id = table["table_id"]
            doc = render.table_doc_markdown(table_id, table, notes.get(table_id) or {})
            self.assertIn("## 5 SQL 约束", doc)
            context.write_text(context.tables_dir(self.root, "stream") / f"{table_id}.md", doc)
        context.write_text(
            context.domain_dir(self.root, "stream") / "navigation.md",
            render.navigation_markdown("stream", skeleton.load(self.root, "stream")),
        )
        context.write_text(
            context.repo_dir(self.root) / "README.md",
            "# Knowledge Base\n\n## domains\n- [stream](domains/stream/navigation.md)\n",
        )

        result = audit.run_audit(self.root, "stream", mode="publish", level="strict")
        self.assertTrue(result["passed"], result["issues"])
        self.assertEqual("oss:oss_kafka", snapshot.latest_snapshot(self.root)["source"])

    def test_component_row_keeps_its_not_applicable_notes_in_the_snapshot(self) -> None:
        snap = snapshot.fetch_metadata(self.root, "stream", source="oss:oss_kafka", runner=kafka_runner())
        for row in snap["tables"]:
            self.assertEqual("oss_kafka", row["_component"])
            self.assertTrue(row[sources.NOT_APPLICABLE], row["table_id"])
            self.assertEqual([], row["COLUMN_BASIC_INFO"])
            self.assertEqual("", row["DDL_SQL"])

    def test_collection_notes_are_visible_in_the_generated_doc(self) -> None:
        """附注不能只活在快照里：表文档要看得见"这类知识为什么没有"。"""
        snap = snapshot.fetch_metadata(self.root, "stream", source="oss:oss_kafka", runner=kafka_runner())
        row = next(t for t in snap["tables"] if t["table_id"] == "rtd_smoke")
        doc = render.table_doc_markdown("rtd_smoke", row, {})
        self.assertIn("**采集说明**", doc)
        self.assertIn("COLUMN_BASIC_INFO：不适用", doc)
        self.assertIn("消息组件没有字段 schema", doc)
        self.assertEqual([], render.missing_sections(doc))

    def test_plain_mock_rows_get_no_collection_note(self) -> None:
        row = {"table_id": "dwd_user_di", "BASIC_INFO": {"owner": "zhangsan"}, "COLUMN_BASIC_INFO": []}
        self.assertNotIn("采集说明", render.table_doc_markdown("dwd_user_di", row, {}))


class VolatileFieldTests(SourcesBase):
    """统计类字段不该被当成知识漂移：真跑时 TABLE_ROWS 在 3 与 0 之间抖过。"""

    def test_row_count_is_not_a_drift(self) -> None:
        old = {"tables": [{"table_id": "t", "BASIC_INFO": {"owner": "a", "row_count": 3}, "COLUMN_BASIC_INFO": []}]}
        new = {"tables": [{"table_id": "t", "BASIC_INFO": {"owner": "a", "row_count": 0}, "COLUMN_BASIC_INFO": []}]}
        self.assertEqual([], snapshot.diff_snapshots(old, new))

    def test_real_identity_change_is_still_a_drift(self) -> None:
        old = {"tables": [{"table_id": "t", "BASIC_INFO": {"owner": "a", "row_count": 3}, "COLUMN_BASIC_INFO": []}]}
        new = {"tables": [{"table_id": "t", "BASIC_INFO": {"owner": "b", "row_count": 0}, "COLUMN_BASIC_INFO": []}]}
        drift = snapshot.diff_snapshots(old, new)
        self.assertEqual(["BASIC_INFO.owner"], [c["field"] for c in drift[0]["changes"]])


if __name__ == "__main__":
    unittest.main()
