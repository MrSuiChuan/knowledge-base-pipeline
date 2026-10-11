# 实时组件知识源

采集这一环原先只有两条路：`mock` 读 `.kb/mock/meta.json`，`live` 调平台元数据 MCP。
两个都只认"平台数仓"这一种形态。本文件记的是第三条路：**直接把主流实时处理组件当知识源**。

## 一、三条纪律

1. **注册表是唯一事实源**。谁能采、采什么、需要哪些连接键、本机验证到哪一层，
   只写在 `engine/sources/registry.json`。连接信息（装在哪、地址是什么）在项目级
   `.kb/config.json` 的 `sources.<组件id>` 下——包里不写死任何主机名与路径。
2. **区分"不适用"与"采失败"**。快照的每一行都可能带两个附注字段：
   `NOT_APPLICABLE`（这个组件压根没有这一类知识，附理由）与 `COLLECT_FAILED`（本该采到但没采到，附原始错误）。
   六类的**值**按契约类型留空（dict→`{}` / list→`[]` / str→`""`），不塞假数据：
   "空"和"编"是两回事。
3. **未登记就不放行**。`oss:<组件id>` 里的组件必须在注册表里；没登记的来源以
   `source_unregistered` 硬门拦下，且**不产生快照文件**。留证撒谎比没有留证更糟。

## 二、组件注册表现状

| 组件 | 角色 | 采集器 | 层级 | 必备连接键 | 本机真跑 |
| --- | --- | --- | --- | --- | --- |
| Apache Kafka | 消息 / 日志存储 | `kafka_cli` | 1 | `bin` / `bootstrap_servers` | 是（2026-10-07） |
| Apache Doris | 实时分析 / 服务层 | `mysql_sql` | 2 | `bin` / `host` / `port` / `user` | 否：未验证 |
| StarRocks | 实时分析 / 服务层 | `mysql_sql` | 1 | `bin` / `host` / `port` / `user` | 是（2026-10-07） |
| ClickHouse | 实时分析 / 服务层 | `clickhouse_sql` | 1 | `bin` / `container` | 是（2026-10-07） |
| Apache Pulsar | 消息 / 日志存储 | — | 3 | `bin` / `service_url` | 否：没有采集器 |
| Apache Flink | 流计算引擎 | — | 3 | `home` / `rest_endpoint` | 否：没有采集器 |

层级是注册表里的 `tier`：1 = 采集器已实现且本机真跑过；2 = 已实现但本机没跑过（状态就写"未验证"）；
3 = 只登记角色与连接形状，**没有采集器**——`sources collect` 会明确报 `collector_not_implemented`，
不返回空结果冒充采到了。

## 三、术语（本层新增三个词）

- **知识源**：一次采集所依据的外部系统。可以是平台元数据 MCP，也可以是某个实时组件。
- **采集器**：把某个组件的元数据翻译成 6 类知识契约的那段代码；按组件登记在注册表里。
- **组件注册表**：`engine/sources/registry.json`，声明"支持哪些组件、怎么连、能采到哪几类、验证到哪一层"的唯一文件。

## 四、怎么用

项目级配置（`.kb/config.json`）：

```json
{
  "sources": {
    "oss_kafka": {
      "bin": "/opt/kafka/bin",                          // 换成你自己机器上的安装目录
      "bootstrap_servers": "127.0.0.1:9092",
      "runner": ["wsl", "-d", "Debian", "--", "bash", "-lc"]
    }
  }
}
```

`runner` 可选：组件只在本机某个执行环境里可达时（例如 WSL 里的 Kafka），
采集命令与探活命令都经同一个 runner，保证"探得到"和"采得到"是同一件事。

三条命令：

```bash
py -3 engine/kbp.py sources list                     # 注册表 + 自检（tier/采集器/理由是否齐全）
py -3 engine/kbp.py sources check --component oss_kafka
py -3 engine/kbp.py sources collect --component oss_kafka   # 试采，不落盘
py -3 engine/kbp.py snapshot fetch --domain stream --source oss:oss_kafka
```

来源也可以写进配置的 `snapshot.source`，之后 `snapshot fetch` / `refresh` 就不必每次带 `--source`。
默认值：显式参数 > `snapshot.source` > 按 `mode` 兜底（`live` → `platform-mcp`，其余 → `mock`）。

## 五、本地实验环境（起组件、跑真采集）

组件不必常驻：要测的时候起，测完停。本机用的是 WSL2 Debian + OpenJDK 21，
Kafka 装在 `~/oss/kafka_2.13-4.1.2`（单机 KRaft）。起停与造数配方：

```bash
# 起（脚本全文见 .tmp/live-source/kafka_up.sh，本次取证用的就是它）
cd ~/oss/kafka_2.13-4.1.2
sed "s|^log.dirs=.*|log.dirs=$HOME/oss/kafka_2.13-4.1.2/lab-data|" config/server.properties > lab-server.properties
test -f lab-data/meta.properties || ./bin/kafka-storage.sh format -t "$(./bin/kafka-storage.sh random-uuid)" -c lab-server.properties --standalone
setsid nohup ./bin/kafka-server-start.sh lab-server.properties > lab-logs/server.out 2>&1 < /dev/null &

# 造两个主题（一个带保留期与最小同步副本，一个带 compact 策略）
./bin/kafka-topics.sh --bootstrap-server 127.0.0.1:9092 --create --if-not-exists \
  --topic kb_smoke_orders --partitions 3 --replication-factor 1 \
  --config retention.ms=604800000 --config min.insync.replicas=2
./bin/kafka-topics.sh --bootstrap-server 127.0.0.1:9092 --create --if-not-exists \
  --topic kb_smoke_clicks --partitions 1 --replication-factor 1 --config cleanup.policy=compact

# 停
./bin/kafka-server-stop.sh
```

## 六、真跑记录（2026-10-07）

环境：WSL2 Debian 13 / OpenJDK 21.0.10 / Kafka 4.1.2 单机 KRaft。

```
$ kbp.py sources check --component oss_kafka   -> rc=0
{"ok": true, "kind": "cmd",
 "target": ".../kafka-topics.sh --bootstrap-server 127.0.0.1:9092 --list",
 "stdout": "__consumer_offsets\nkb_smoke_clicks\nkb_smoke_orders\nrtd_lab_smoke\n..."}

$ kbp.py sources collect --component oss_kafka -> rc=0
{"tables": 7, ...}      # 7 个主题：本次建的 2 个 + 历史实验留下的 5 个

$ kbp.py snapshot fetch --domain stream --source oss:oss_kafka -> rc=0
metadata-snapshot-2026-10-07T042926Z.json
  source = oss:oss_kafka | tables = 7
  - kb_smoke_orders      分区=3 副本=1 保留=7.0天 规则=['retention_ms','min_insync_replicas'] 采失败=[]
  - kb_smoke_clicks      分区=1 副本=1 保留=None天 规则=['cleanup_policy','min_insync_replicas'] 采失败=[]
```

`kb_smoke_orders` 的完整快照行（节选）：

```json
{
  "table_id": "kb_smoke_orders",
  "BASIC_INFO": {"domain": "stream", "layer": "log", "frequency": "streaming", "owner": "unknown", "partitions": 3, "replication_factor": 1},
  "QUALITY_RULE": [{"rule": "retention_ms", "value": 604800000}, {"rule": "min_insync_replicas", "value": 2}],
  "PARTITION_INFO": {"partition_column": "<消息 key 的哈希>", "type": "key-hash", "partitions": 3, "retention_days": 7.0},
  "NOT_APPLICABLE": {"COLUMN_BASIC_INFO": "消息组件没有字段 schema；…不在 broker 里", "DDL_SQL": "…", "SCHEDULE_TASK": "…"},
  "_component": "oss_kafka"
}
```

## 七、真链路（2026-10-07）：从组件到知识文档

采到快照只是第一步。组件来源的行天生带空洞（消息组件没有字段、没有 DDL、没有调度），
所以还要证明这种形状能走完后半程。同一天在同一台机器上跑完整条：

```
$ kbp.py sources check --component oss_kafka        -> rc=0（7 个主题）
$ kbp.py snapshot fetch --source oss:oss_kafka      -> metadata-snapshot-2026-10-07T054652Z.json（source=oss:oss_kafka，7 表）
$ kbp.py skeleton set --json-file skeleton.stream.json
$ kbp.py generate --domain stream                   -> 写出 7 份 9 章节表文档
$ kbp.py audit --domain stream --mode publish --level strict
    -> rc=0，passed=True，issues=[]
       六层链接：L1 scanned=1 / L2 scanned=2 / L3 scanned=2，broken 全为空
```

生成的 `domains/stream/tables/kb_smoke_orders.md` 第 1 节直接来自 broker 回读：

```
- domain: stream  - layer: log  - frequency: streaming  - owner: unknown
- partitions: 3   - replication_factor: 1
- 分区: <消息 key 的哈希> / key-hash / 保留 7.0 天
```

测完组件已停（`kafka-server-stop.sh`），本机不留常驻进程。

## 八、服务层真跑（StarRocks + ClickHouse，2026-10-07）

服务层比消息层"更像表"：有库、有字段、有类型与注释、有分区、有建表语句。两家都用容器镜像路线
（官方发行包拿不到，Doris 那条有已记录的内存卡点）。

### StarRocks（复用相邻插件已验证过的编排）

```bash
# 起（脚本全文见 .tmp/live-source/starrocks_up.sh）
sysctl -w vm.max_map_count=2000000          # BE 前置；WSL 重启后要重设
bash <realtime-data-plugin>/tools/lab/serving_cluster_up.sh up \
  --fe-image docker.1ms.run/starrocks/fe-ubuntu:3.3.9 \
  --be-image docker.1ms.run/starrocks/be-ubuntu:3.3.9 \
  --prefix kb-sr --network kb-sr-net --mysql-port 9030
mysql -h127.0.0.1 -P9030 -uroot -e "ALTER SYSTEM ADD BACKEND '<BE 容器 IP>:9050';"   # 编排脚本这次没等到心跳，手工补注册
# 停
bash <realtime-data-plugin>/tools/lab/serving_cluster_up.sh down --prefix kb-sr
```

结果：

```
$ kbp.py sources check --component oss_starrocks    -> rc=0（cmd：mysql -e "SELECT 1"）
$ kbp.py sources collect --component oss_starrocks
    字段 6 个 | DDL 639 字符 / 18 行 | 不适用 [QUALITY_RULE, SCHEDULE_TASK] | 未采到 []
$ kbp.py snapshot fetch --domain serving --source oss:oss_starrocks -> source=oss:oss_starrocks
$ kbp.py refresh --domain serving
    检出 COLUMN_BASIC_INFO.status.comment: '订单状态' -> '订单状态（终态）'，rewritten=[orders_by_minute]
```

生成的表文档第 1 节末尾多了采集说明（这就是 KBP-026 要的效果）：

```
**采集说明**（这一行的六类知识是怎么来的）
- QUALITY_RULE：不适用 —— 质量规则不在组件内；组件内的等价物是表属性，已落在 DDL_SQL
- SCHEDULE_TASK：不适用 —— 调度不在组件内，在上游任务系统；组件只提供查询与存储
```

**真跑才暴露出来的四件事**（都已修掉或写进注册表 gaps）：

1. **内部库不止一个**：StarRocks 还有 `_statistics_`，不排除就把系统表当业务表采进来（一次采到 9 张"表"，8 张是内部表）。
2. **中文注释把输出读崩了**：Windows 默认按 GBK 解码子进程输出，`UnicodeDecodeError` 让字段表和 DDL 直接变空。必须显式 `encoding="utf-8"`。
3. **反引号在 `wsl.exe → bash -lc` 这一层被吃掉**：`SHOW CREATE TABLE \`db\`.\`t\`` 变成 `SHOW CREATE TABLE .`（bash 把反引号当命令替换）。根治办法是 SQL 走 stdin，不进命令行。
4. **DDL 是真换行**：`--raw` 下建表语句跨 18 行，只取首行会把它截成 `CREATE TABLE x (`。

外加两条操作性结论，写进注册表 gaps：

- **注释类改动有传播延迟**：`ALTER … MODIFY COLUMN … COMMENT` 完立刻采集读到的还是旧注释，约 45 秒后才可见；字段增减则立刻可见。所以"改完就采"可能采到旧值，反哺要留出重采窗口。
- **统计字段会抖**：`information_schema.TABLES.TABLE_ROWS` 在 3 与 0 之间来回，若参与漂移比对，每次反哺都会报一次假变化。现在 `row_count` 明确不参与漂移判定（文档里照常展示）。

### ClickHouse（单容器，最省事的一家）

```bash
# 起（脚本全文见 .tmp/live-source/clickhouse_up.sh）
docker run -d --name kb-ch -p 8123:8123 -p 9000:9000 clickhouse/clickhouse-server:24.8
docker exec -i kb-ch clickhouse-client --multiquery <<'SQL'
CREATE DATABASE IF NOT EXISTS kb_stream;
CREATE TABLE IF NOT EXISTS kb_stream.clicks_by_minute (
  window_start DateTime COMMENT '窗口起点',
  click_cnt    UInt64   COMMENT '点击数',
  channel      String   COMMENT '渠道'
) ENGINE = MergeTree PARTITION BY toYYYYMMDD(window_start) ORDER BY (window_start, channel)
COMMENT '每分钟点击数（本地实验）';
SQL
# 停：docker rm -f kb-ch
```

采集结果：

```
$ kbp.py sources check --component oss_clickhouse   -> rc=0（docker exec … clickhouse-client --query "SELECT 1"）
$ kbp.py sources collect --component oss_clickhouse
    表 kb_stream.clicks_by_minute | 字段 3 个 | DDL 314 字符 / 11 行 | 分区 1
    | 不适用 [QUALITY_RULE, SCHEDULE_TASK] | 未采到 []
$ kbp.py snapshot fetch --domain serving --source oss:oss_clickhouse -> source=oss:oss_clickhouse
```

ClickHouse 这一家另外踩到两点（都已修，且各有用例）：

1. **列名里有保留字**：`system.columns` 的列名就叫 `table`，必须用反引号——而 SQL 走 stdin，
   所以反引号不会经过任何 shell（这正是前面那条纪律的第二个用处）。
2. **TabSeparated 会转义**：语句里的换行变 `\n`、单引号变 `\'`。不还原的话，生成的文档里会出现
   `COMMENT \'窗口起点\'` 这种带反斜杠的怪样子。

## 九、测试覆盖（`tests/test_sources.py`，40 个用例，全部用桩）

| 组 | 条数 | 钉住什么 |
| --- | --- | --- |
| RegistryTests | 5 | 注册表自检、6 类顺序、未登记组件被拒、tier 3 硬报错、缺连接键指名 |
| KafkaCollectorTests | 4 | 主题→契约映射、不适用≠空对象、空主题不算成功、失败带原始原因 |
| SourceGateTests | 4 | 快照来源如实记录、可来自配置、未登记来源不落盘、mock 不冒充 platform |
| MysqlCollectorTests | 8 | 服务层映射、分区失败不算"没有分区"、DDL 上限/开关可见、多行 DDL 不被截断、内部库过滤按组件走、空库不算成功、密码只传一次 |
| ClickHouseCollectorTests | 5 | 契约映射、TabSeparated 转义还原、分区失败不算没有分区、docker exec 形状与 SQL 不过命令行、空实例不算成功 |
| ProbeTests | 4 | tcp 通/断、http fail-closed、cmd 问组件本身、runner 前缀拼成单参数 |
| SourcesCliTests | 4 | list 干净、未实现采集器 rc=3、未登记来源 rc=3 且不落盘、缺键 rc=3 |
| ComponentSourcedPipelineTests | 4 | 组件来源快照走完后半程、附注随行进快照、附注进生成的文档、普通行不出现采集说明 |
| VolatileFieldTests | 2 | `row_count` 不算漂移、真正的身份变化仍然算 |

全量 `py -3 -m pytest tests -q` → **111 passed**。

## 十、边界（如实标注，不推断补齐）

- **属主不在 broker**：主题的 owner 记 `unknown`，属主在平台数据目录里；知识库里的人工章节可以补，采集层不编。
- **消息 schema 需要 Schema Registry**：没有它就没有字段语义，所以 `COLUMN_BASIC_INFO` 明确标 `NOT_APPLICABLE`，
  而不是留一个空表让人以为"没字段"。
- **保留期只报显式配置**：没有显式 `retention.ms` 的主题报 `None`（走的是 broker 默认值），不替它算一个默认值。
- **未验证的组件**：Doris / StarRocks 的采集器已实现但本机没跑过，注册表里写 tier 2；
  ClickHouse / Pulsar / Flink 还没有采集器，写 tier 3。
- **schema 命名**：消息组件的 `schema` 一律记为 `kafka` 这类组件名（消息组件没有库的概念），
  表级文档按主题名生成，不虚构库名。
