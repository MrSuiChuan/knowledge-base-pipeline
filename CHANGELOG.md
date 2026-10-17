# Changelog

## [Unreleased]

<!-- 下一条改动写在上面这一节 -->

### Added（会话记忆自动捕获：对齐 OpenViking 官方 Codex 插件，2026-10-17）

官方为 Codex 提供 `openviking-memory` 插件，用 6 个生命周期事件把记忆做成自动链路
（SessionStart 注入 / UserPromptSubmit 召回 / Stop 逐轮捕获 / PreCompact 与 SessionEnd 提交 /
PreToolUse 提示）。本插件此前只有 3 个事件且全靠手工 `memory add`，所以"实时同步"从未发生。

- **`Stop` 逐轮捕获**（`hooks/stop.py` + `memory capture`）：解析 Codex rollout JSONL，
  只取 user/assistant 文本，按每会话水位去重；transcript 被 `/compact` 重写时从最近一条
  user 轮次续接，不整段重放；
- **`UserPromptSubmit` 自动召回**（`hooks/userpromptsubmit.py` + `memory recall`）：
  按本轮 prompt 检索 `viking://user`，以 `<openviking-memory>` 紧凑块注入
  `hookSpecificOutput.additionalContext`；失败静默（fail-open）；
- **阈值提交**：`pending_tokens >= ov.commit_token_threshold`（默认 2 万）才 commit，
  避免每轮消耗模型配额；
- **`PreCompact` / `SessionEnd` 提交**（`hooks/precompact.py`、`hooks/sessionend.py`）；
  SessionEnd 需要 Codex ≥ 0.145，本机 0.135 由 SessionStart 的空闲清扫兜底；
- **`SessionStart` 空闲清扫**：超过 30 分钟未捕获的会话补捕获并提交（最多 3 个/次）；
- **配置与官方对齐**：`ov.url` 为空时回退读 `~/.openviking/ovcli.conf` 的
  `url/api_key/account/user`；
- 新增配置项：`auto_capture`、`auto_recall`、`capture_mode`、`commit_token_threshold`、
  `recall_limit`、`recall_timeout_s`、`session_idle_ttl_minutes`（均只在
  `memory_enabled=true` 时生效）。

回归：`tests/test_memory_hooks.py` 11 条（假 OV 服务端，不依赖外网）+ 全量 180 条
（3.9 与 3.12 两端）；差距与验收见 `docs/session-memory-hooks-ledger.md`。
**尚未做真实实例联调**：`<openviking-host>:1933` 当前 TCP 不可达（22/80/443/1933 全 filtered）。

### Fixed（插件测试跑出来的三处真问题，2026-10-14）

用一份 119 条用例的测试实验台逐条跑本插件的七个环节与 hook 门控，三处不通过：

- **`setup` 幂等**（`engine/core/context.py`、`engine/kbp.py`）：旧实现无条件重写
  `.kb/config.json` 与机器状态文件，用户填的 owners / ov / sources 与
  `last_audit` / `last_publish` / `seq` 会被静默清空（发布版本号还可能因此重复）。
  setup 是技能文档里让 agent 反复跑的入口，「再跑一次就好」不能带副作用；
  现在只在缺文件时写入。`setup` 的输出也改成报**落盘后的实际配置**，
  不再把这次请求的参数当成结果；
- **审计级别按「不低于配置要求」判**（`engine/core/audit.py`）：配置 `audit_level=standard`
  而审计跑了 `--level strict` 时，旧实现按「必须完全相等」判，更严的审计反被
  `kb_publish_guard` 拦死，理由还是「strict != standard」。现在 strict 满足 standard，
  反方向（审计低于要求）照旧拦；
- **记忆命令先报「没启用」**（`engine/core/ov_memory.py`）：未启用时
  `memory status` / `commit` / `mark_used` 先回的是「先跑 memory begin」，
  而 begin 又会回「没启用」——门指错了方向。现在配置门（未启用 / 缺地址）先于会话门。

回归用例：`tests/test_engine.py::SetupIdempotencyTest`、
`PublishGateTests::test_stricter_audit_satisfies_lower_configured_level`（与反方向一条）、
`tests/test_memory.py::DisabledPrecedenceTest`。

另有一条**没有单方面改**的缺口记在测试台账里（观察项 O-4）：消费方开发插件项目里
没人创建 `.rtd/mock/kb/index.json` / `.data-dev/mock/kb/index.json`，而生产端按设计
「只写已存在的索引」，所以首次 `publish --consumer-root` 必然报 `consumer_sync.ok=false`。
改哪一侧（消费端初始化时建空索引 / 生产端首次 seed）需要业主拍板。

### Changed（README 重排：按"你想干的事"分层）

原来的 README 把"30 秒跑通"和"改完代码怎么让宿主加载新版本"挤在同一层，文件里塞了大量
只有改插件的人才需要的细节，反而没有一处写清"它做不到什么"。

- **开头加一张分流表**：想先跑通 / 想真用起来 / 想懂设计 / 想改代码，四条路各指一处；
- **补三块缺的内容**：「它解决什么问题」（知识与会话记忆两条链路的落点对比）、
  「装之前要有什么」（前置条件清单）、「已知边界」（捕获靠命令驱动、`commit` 会花钱、
  实时组件分三层且 Doris 未验证、`rules/` 不许手改、hook 失败会被当放行）；
- **合并重复**：环境 / 安装 / 装完必做 / 三条命令，压成「快速开始」下面的四小节；
  双宿主差异从长段落改成一张表加三条；
- 只有改插件的人才需要的（cachebuster 重装、生成物不许手改）压成「改完插件代码」一节，
  详细规矩仍在 [CONTRIBUTING.md](CONTRIBUTING.md)；
- `docs/README.md` 里指向"README 的发布一节"的链接改指到新的「日常命令」表。

### Added（/kb-remember 记会话 + 就绪前置门 + 接入说明）

- **新命令 `/kb-remember`**（Codex 入口 `kbp-remember`，由 `commands/remember.md` 生成）：
  把这一轮的要点批量写进当前会话，收工前再 `memory commit` 触发抽取。
  命令里写清了"要写什么、不要写什么"（偏好/口径/环境事实要写；密钥、内网地址、真实数据不写），
  以及汇报要求（`memories_total`、`llm_tokens`、留证路径；`extraction_note` 非空要原样告诉用户）。
  顺带修掉生成器的硬编码清单：`COMMAND_NAMES` 少了 `remember`，新命令不会被转成 Codex 技能。
- **`memory commit` 新增就绪前置门**：提交前先探 `GET /ready`，未通过就报 `memory_not_ready`
  并**拒绝提交**——避免"白提交一次、留下看起来成功的留证"（本机那台余额 402 就是这么坑的）。
- **SessionStart 提示补一句**："收工前跑 `memory commit`"（仅在 `memory_enabled` 时），
  否则这件事永远靠人记得。
- **接入说明**：`docs/session-memory.md` 新增"日常怎么用（接到线上实例）"——
  配置片段 + 三处分辨两台实例的判据（`version` / `auth_mode` / `account_id`）+ 误连后的处置。

### Fixed（ov-check 看不出"就绪"：扁平 /health 被解包成 null）

对着**线上实例**做自检时发现的真缺口：`ov-check` 报 `ok: true` 却带着 `health: null`，等于什么都没看到。

- 根因一：`/health` 是**扁平**返回（`{"status":"ok","healthy":true,"version":"0.4.11","auth_mode":"api_key"}`），
  没有 `result` 信封，走 `request()` 会被解包成 `None`。
- 根因二：只看 `/health` 也判断不出"就绪"——embedding 不可用时 `/ready` 给 503，而 `/health` 照旧 200。
- 现在 `ov-check` 输出：`health`（原样保留扁平 payload）+ `health_http`，以及 `ready` + `ready_http` + `ready_ok`。
  对线上实例实测：`ready_ok=true`、`ready.checks.embedding="ok"`、`vectordb="ok"`。
- 用例 3 条：扁平 health 要被保留、未就绪必须如实报 false（服务本身仍算通）、连不上要报传输错误。

### Added（会话记忆真跑验证 + 一处诚实性修复）

本机 `openviking-server`（0.3.24，绑 127.0.0.1:1933，dev 模式）真跑了一遍完整链路：
建会话 → 追加消息（服务端回读 `message_count` 1→2）→ `commit`（`status=accepted`、
`archive_uri=viking://session/<id>/history/archive_001`）→ 后台 `session_commit` 任务 `completed`
→ 回读 `commit_count=1`。磁盘上 `session/<id>/history/archive_00{1,2}/` 与
`agent/default/memories/` 都可核对。**归档链路通了。**

- **记忆抽取失败的原因不在插件**：服务端日志给出 `402 insufficient_balance_error`——
  抽取与 embedding 走 `ov.conf` 里的 MiniMax 配额，该账户**余额不足**，所以
  `Extracted 0 memories`、`llm_token_usage` 为 0。归档不花模型因此成功。
  充值（或换可用的 embedding/vlm 端点）后重跑即会产出记忆。
- **修掉一处诚实性缺口**：服务端在抽取失败时仍把任务标成 `completed`，早先实现据此报
  `extraction_ok: true`，等于把失败报成成功。现在 `memory commit` 改报
  `task_ok / memories_total / llm_tokens / extraction_note`——零产出零用量时给出提醒，
  不再默认成功（判据只看**抽出的条目数**与**LLM 用量**两个信号）。
- 文档 [docs/session-memory.md](docs/session-memory.md) 新增第六节：真跑逐步记录、402 根因、
  以及上面这条判据。
- 用例补 3 条（完成但零产出要提醒 / 有产出不算失败 / 任务失败不算 OK），`tests/test_memory.py` 21 passed。

### Added（会话记忆：把会话记进 OpenViking 并触发记忆抽取）

**背景（诊断）**：本插件原先对 OpenViking 只用文件接口，写入作用域只有
`viking://resources/`（已定稿的知识成品）。OpenViking 的记忆是另一条链路——
会话 → 追加消息 → `commit` → 后台抽取记忆 → `user/<id>/memories` 与 `agent/<id>/memories`——
本插件从未调用。所以"没有会话记忆"不是故障，是**没接**。

- 新增 `engine/core/ov_memory.py`：会话生命周期（create / add_message / add_messages 分批 /
  commit / get_task / wait_task / get_session / extract / used），复用既有 `ov.*` 配置与密钥来源，
  不新开第二套读取路径。
- 新增 `kbp.py memory` 动词：`begin` / `add` / `batch` / `commit` / `used` / `status`；
  `commit` 默认轮询后台抽取任务到终态，超时如实报 `memory_task_timeout`。
- 配置新增 `ov.memory_enabled`（**默认关**：commit 会消耗模型配额）、
  `ov.keep_recent_count`、`ov.task_timeout`。
- `SessionStart` hook 在启用时自动 `begin`（复用已有会话），**fail-open**：
  记忆链路任何异常都静默跳过，不影响会话启动。
- 留证：`.kb/runtime/memory/session.json`（绑定与提交历史）与
  `.kb/runtime/memory/commit-<ts>.json`（提交结果 + task 终态；**超时也照写**——归档确实发生过）。
- 用例：`tests/test_memory.py` 16 条（请求形状 / 101 条自动分批 / 留证内容 /
  未启用 / 无会话 / 空批次 / 任务超时仍留证 / 服务端错误信封）。
- 文档：新增 [docs/session-memory.md](docs/session-memory.md)，写清两条路的区别、
  接口来源（取自本机 0.3.24 服务端路由定义，不是猜的）、**捕获是命令驱动而非自动**这一边界，
  以及"commit 会花钱"的成本提示。

### Fixed（本机地址不再强制要 API Key）

做会话记忆时发现一个会让本地部署"装好即不可用"的问题：客户端原来一律要求 API Key，
而本机 OpenViking 是 **dev 模式**（服务端 `server/auth.py`："Dev mode: no authentication,
always return ROOT"），`ovcli.conf` 里根本没有密钥。现在 `127.0.0.1` / `localhost` / `::1`
允许空 key，且不再发空的 `X-API-Key` 头；**非本机地址仍然强制要 key**。
契约变化同步改了用例（`tests/test_remote.py` 保留远端反例，本机正例新增），
`tests/test_memory.py` 也加了对应断言。

### Fixed（真实仓库联调暴露的两个真问题）

在 `data-warehouse-learning`（电商数仓，含真实 Doris/Flink SQL）上跑全流程时卡住两处，都已修并补回归：

- **外部提案 JSON 不带 `proposal_id` 时写成 `None.json`**：`proposals.apply_proposal` 直接拿
  `proposal.get("proposal_id")` 拼文件名，于是提案落库了、`rule approve --proposal-id <号>`
  永远找不到它——沉淀链路断在最后一步。现在入口处按 `default_proposal` 的规则补号
  （回归：`ProposalTests::test_proposal_without_id_gets_one_from_the_engine`）。
- **audit 的规则引用正则把中文词「活动规则ID」当成规则号**：原写法 `规则:?[\s:：]*([A-Z]…)`
  允许"规则"和 ID 之间没有分隔符，真实 DDL 注释里的「活动规则ID」被解析成规则 `ID`，
  报一条不存在的断链，直接拦住发布。现在要求带分隔符
  （`规则\s*[:：]\s*([A-Z][A-Z0-9_-]+)`），并补两条回归：该忽略的忽略、真断链仍要红。

### Fixed（开源自检的两处误报）

`tools/validate_oss.py` 的"无个人路径"一项在给姊妹仓库补同一套检查时暴露两处误报，
两处都会把**已经写对**的内容判成泄漏：

- `/home/u/`、`/home/lab/` 这类**占位用户名**（realtime-data-plugin 的用例里就在用）不再误报；
- `C:\Users\...\` 这种**已脱敏**写法不再误报（rtd 的 `docs/validation-report.md` 引用宿主报错原文即如此）。

判定改为"先看是不是占位/脱敏写法"；`tests/test_oss_readiness.py` 的反例用例继续钉住真泄漏。

## [1.3.0] - 2026-10-07

### Added（ClickHouse 采集器）

采集层缺的三家里先补最像"表"的一家。ClickHouse 与 Doris/StarRocks 同属服务层，但客户端、
系统表与输出转义都不同，照搬 MySQL 那套会翻车：

- 新增 `clickhouse_sql` 采集器：`system.tables` / `system.columns` / `system.parts` +
  `SHOW CREATE TABLE`，映射进原有 6 类契约；调度与质量规则按 `NOT_APPLICABLE` 如实标注。
- 客户端经 `docker exec -i <容器> clickhouse-client` 调用，**SQL 走 stdin**——
  这是 KBP-016 那条纪律的第二个用处：`system.columns` 的列名 `table` 是保留字要用反引号，
  SQL 不过 shell 就没人会把它当命令替换。
- 真跑暴露并修掉两点：① 保留字列名（同上）；② TabSeparated 把换行转义成 `\n`、
  单引号转义成 `\'`，不还原会让生成的文档出现 `COMMENT \'窗口起点\'` 这种带反斜杠的怪样子。
- 真跑取证：`clickhouse/clickhouse-server:24.8` 单容器 → `sources check` rc=0 →
  采集到 `kb_stream.clicks_by_minute`（3 个字段含中文注释、DDL 314 字符 / 11 行、分区 1、
  未采到为空）；注册表 `oss_clickhouse` 从 tier 3 升到 **tier 1**。
- 用例：`ClickHouseCollectorTests` 5 条；`tests/test_sources.py` 40 passed。

### Added（开源就绪：按 Apache 项目标准补齐并加机器检查）

按 Apache 项目（ASF 风格）的通行标准做了一次全面排查与优化，四维度逐条给结论（见
[docs/apache-readiness-audit.md](docs/apache-readiness-audit.md)）：

- **许可与声明**：`LICENSE` 从 MIT 换成 **Apache-2.0 官方全文**、新增 `NOTICE`、
  `engine/` `hooks/` `tools/` `tests/` 共 **30 个自研源文件加逐文件许可头**；
  两份 `plugin.json` 的 `license` 字段同步为 `Apache-2.0`——顺带修掉一处漂移：
  生成器原先**硬编码** `author`/`license`，换许可时两份清单会对不上，
  现在与版本号一样从 Claude 清单一处读。
- **治理与流程**：新增 `GOVERNANCE.md`（角色 / 惰性共识 / 需要更强共识的四类事项 /
  争议升级 / 弃用）、`CODE_OF_CONDUCT.md`、`SUPPORT.md`、`docs/release-process.md`（可照抄的发版 6 步）。
- **贡献入口与安全**：新增三个 issue 模板（bug / feature / 配置求助）+ `config.yml`（关掉空白 issue）
  + PR 模板 + `CODEOWNERS`；`SECURITY.md` 改为同时覆盖公开期（GitHub Private vulnerability
  reporting）与私有期，并给出响应时点。
- **友好性**：新增 `docs/README.md`（文档地图，按"你手上是什么问题"组织）与
  `docs/glossary.md`（14 个本仓库特定含义的词 + 4 条常见误解）；README 补「参与与支持」，
  `README.en.md` 对齐。
- **第三方与商标边界**：新增 `docs/third-party-dependencies.md`（仓库内包含什么 /
  测试时在谁的机器上跑什么 / 商标声明），与 `NOTICE` 口径一致。
- **机器检查**：新增 `tools/validate_oss.py`（5 项：文件齐全 / LICENSE 与 NOTICE /
  清单字段与署名一致 / 许可头 / 无个人路径），挂进 CI；
  新增 `tests/test_oss_readiness.py`（1 正例 + 3 反例，证明这道检查不是摆设）。
- **脱敏**：清掉文档与台账里的维护者本机绝对路径（真跑取证时写进去的），并把个人路径纳入自检。

约束：全历史（14 个提交）patch 级扫描无字面密钥——唯一命中是
`self.api_key = str(settings["api_key"])`，从环境变量/密钥文件读取，不是硬编码。

**需要所有者拍板**：MIT → Apache-2.0 是法律状态变更（多了明示专利授权与声明义务），
回滚需同时改六处，清单见审计报告第七节。

### Added（服务层真跑：StarRocks 采集 + 组件侧漂移反哺 + 附注进文档）

上一轮的服务层采集器只是"写好了"，这一轮拿真组件验完，并顺手修掉真跑才暴露的四个缺陷：

- **服务层真跑（StarRocks 3.3.9，FE/BE 各一容器）**：`sources check` 走 mysql 客户端
  `SELECT 1`（问组件本身）→ 建库建表写 3 行读回 3 行 → 采集到 **6 个字段（含中文注释）
  与 639 字符 / 18 行的 DDL**，`不适用 [QUALITY_RULE, SCHEDULE_TASK]`、未采到为空。
  注册表 `oss_starrocks` 从 tier 2 升到 **tier 1**；`oss_doris` 保持 tier 2（未验证，
  容器路线有已记录的内存卡点），不假装跑过。
- **真跑暴露的四个缺陷，全部已修**：① 内部库过滤改为按组件声明（StarRocks 多一个
  `_statistics_`，首次采集把 8 张系统表当成了业务表）；② 子进程输出显式 `utf-8`
  （Windows 默认 GBK 解码中文注释直接抛 `UnicodeDecodeError`，字段表与 DDL 变空）；
  ③ **SQL 改走 stdin**（反引号在 `wsl.exe → bash -lc` 这一层被吃掉，`SHOW CREATE TABLE`
  被打成 `SHOW CREATE TABLE .`）；④ DDL 按多行解析（`--raw` 下真换行，只取首行会截断）。
- **组件侧漂移走同一条反哺链路**：加字段立刻可见（`COLUMN_BASIC_INFO.pay_amount: null -> added`）；
  改注释实测有传播延迟，约 45 秒后才可见——这条操作纪律写进了注册表与文档。
- **不再有假漂移**：`information_schema.TABLES.TABLE_ROWS` 会在 3 与 0 之间抖，原先每次反哺
  都报一次变化；现在 `row_count` 明确不参与漂移判定（文档里照常展示）。
- **采集附注进表文档**：`NOT_APPLICABLE` / `COLLECT_FAILED` 不再只活在快照里，
  表文档第 1 节末尾出现「采集说明」，逐条写明哪类知识不适用/未采到及原因；
  9 章节结构不变，普通 mock 行不出现该块。
- 用例 28 → **35**（服务层 8、探活 4、命令层 4、端到端 4、易变字段 2 …）；
  全量 `pytest` 95 → **102 passed**。

### Added（实测加厚：组件来源的快照能走完后半程）

上一轮把实时组件接进采集层，这一轮把它测厚并跑完整条真链路：

- **服务层采集器的用例**（原先是零覆盖）：库表/字段/分区/DDL 映射，加上反例——
  `information_schema.PARTITIONS` 查询失败要报 `COLLECT_FAILED` 而不是当成"没有分区"；
  `max_ddl_tables` 截断与 `with_ddl=false` 都要在行上可见（顺手修掉 `with_ddl=false`
  让 DDL 静默为空这处沉默）；客户端密码恰好传一次。
- **探活与执行环境**：tcp 通/断、http 探不可达必须 fail-closed、cmd 型探活问的是组件本身
  （`kafka-topics.sh --list`，不是只看端口）、`runner` 前缀把命令行拼成单个参数。
- **命令层接口**：`sources list` 的 `problems`、未实现采集器 `rc=3 /
  collector_not_implemented`、未登记来源 `rc=3 / source_unregistered` 且不落盘、缺连接键
  `rc=3` 并回 `missing` 列表。
- **端到端**：`tests/test_sources.py::ComponentSourcedPipelineTests` 证明组件来源的快照
  （六类里有三类为空）能生成表文档并通过严格审计。
- 用例 13 → **28**；全量 `pytest` 80 → **95 passed**；引擎清单与 Codex 面同步重生成。

**真链路（2026-10-07）**：真 Kafka 4.1.2 起 broker → `sources check` rc=0（7 主题）→
`snapshot fetch --source oss:oss_kafka`（7 表）→ `skeleton set` → `generate` 写出 7 份
9 章节表文档 → `audit --mode publish --level strict` **rc=0 / passed=True / issues=[]**
（六层链接 L1/L2/L3 全无 broken）。记录见 [docs/realtime-sources.md](docs/realtime-sources.md) 第七节；
测完组件已停。

另做一次跨插件登记核对：本插件登记的 6 个组件与 realtime-data-plugin 的
`governance/oss-components.json` 逐个比对，**共有组件的角色全部一致，没有矛盾**；
只在对方登记的 7 个（debezium/delta/fluss/hudi/iceberg/paimon/spark）是后续候选。
两边的 tier 口径不同（本插件按"知识采集能不能做"，对方按"本机跑没跑过"），已在台账写明不比对。

### Added（实时组件知识源：采集不再只认平台 MCP）

采集这一环原先只有两条路：`mock` 读 `.kb/mock/meta.json`，`live` 调平台元数据 MCP。
两个都只认"平台数仓"一种形态，主流实时处理组件的元数据没有任何接入点。本次把"实时组件"
补成一等知识源：

- **组件注册表** `engine/sources/registry.json`：谁、什么角色、用哪个采集器、需要哪些连接键、
  本机验证到哪一层（tier 1 已真跑 / 2 已实现未跑 / 3 只登记形状），只写这一份；
  连接信息来自项目级 `.kb/config.json` 的 `sources.<组件id>`，包里不写死路径与主机名。
- **采集适配层** `engine/core/sources.py`：把组件元数据翻译成原有 6 类知识契约。
  两类附注字段随行进快照——`NOT_APPLICABLE`（组件压根没有这类知识，附理由）与
  `COLLECT_FAILED`（本该采到却失败，附原始错误）；六类的值按契约类型留空，不塞假数据。
- **来源可插拔**：`snapshot fetch --source mock|platform-mcp|oss:<组件id>`，也可写进配置的
  `snapshot.source`。未登记的来源以 `source_unregistered` 拦下且不落盘。顺带修掉一处留证撒谎：
  mock 模式的快照原先也把 `source` 写成 `platform-mcp`，现在如实写 `mock`。
- **新动词** `sources list`（注册表 + 自检）/ `sources check`（就绪探测）/ `sources collect`（试采，不落盘）。
- **已实现的采集器**：Kafka（本机真跑）、Doris / StarRocks（共用 MySQL 协议采集器，本机未跑，
  注册表如实标 tier 2）；ClickHouse / Pulsar / Flink 只登记角色与连接形状，调用即报
  `collector_not_implemented`，不假装支持。
- **测试**：新增 `tests/test_sources.py`（13 个用例，全部用桩，不依赖本机装组件）——
  注册表自检、未登记组件被拒、未实现采集器硬报错、缺连接键指名、Kafka 契约映射、
  "不适用≠采失败"、空结果不算成功、快照来源如实记录、未登记来源不落盘。

真跑取证（2026-10-07，WSL2 + Kafka 4.1.2 单机 KRaft）：起 broker → 建两个主题 → 真实采集 →
`metadata-snapshot-2026-10-07T042926Z.json`（`source=oss:oss_kafka`，7 个主题，分区/副本/保留期/
最小同步副本都来自 broker 回读）。配方与原始输出见 [docs/realtime-sources.md](docs/realtime-sources.md)。

### Fixed（hook 关键词误伤：只读分析不再被当成裸调 CLI）

`engine/core/gates.py` 的 `analyze_command` 原先对**整条命令做子串匹配**：
`re.search(r"kbp\.py|kb-publish|openviking|data-quality-kb-maintain", 整条命令)`。
后果是只要命令文本里出现这些词就被认定成"未初始化就裸调知识库 CLI"。接管期间实测被拦两次：

- `rg -n "^def verb_" engine/kbp.py` —— 纯只读检索，因为路径里含 `kbp.py`；
- 打印一行 `=== OpenViking ... ===` 当输出标题 —— 只是提到一个词。

更糟的是 `kb-publish` 是**技能名**：任何提到它的命令都会命中"按发布处理"，
进而去查审计新鲜度，陈旧就 block。

现在只认三种**真调用**形态：段首就是引擎脚本、段首是 python 启动器且后面跟着引擎脚本、
段首是知识库/OV 的 CLI 可执行名（含 `FOO=1 sudo` 这类前缀）。新增
`tests/test_engine.py::CliInvocationTests`（3 个用例）钉住两种形态。

### Added（引擎完整性自检 + 生成物/版本号同步门 + 重装路径 + 跨平台）

- **引擎完整性**：新增 `tools/generate_engine_manifest.py` 与 `engine/.engine-manifest.json`；
  `kbp.py` 每次启动核对项目内的 `.kb/engine` 副本，不一致即以 `engine_integrity` 拒绝继续
  （实测篡改 `core/gates.py` 后返回码 4）。没有副本/清单时返回空，不误报。
- **生成物同步门**：新增 `tests/test_generated_surface.py`，把生成器输出截在内存里与仓库
  文件逐字节比对。此前仓库里的 `.codex-plugin/plugin.json` 是 `\uXXXX` 转义、生成器输出
  UTF-8——漂移早就存在，只是没人看见。
- **版本号单一来源**：生成器不再硬编码 `VERSION`，改从 `.claude-plugin/plugin.json` 读；
  新增断言（Claude 清单 == Codex 清单 `+` 前的基础版本 == CHANGELOG 最新已发布小节）。
- **重新安装路径**：新增 `tools/reinstall.py`（默认预演，`--apply` 才动手），
  README 补「改完插件代码怎么让宿主加载新版本」。
- **跨平台**：`tools/adapt_hooks.py` 重写（直接改 JSON 启动器词 + 新增 `--check`），
  新增 `tests/test_hook_wiring.py` 真跑 `hooks.json` 里的命令；CI 增加 ubuntu+windows
  双平台 hooks job，主 job 改成 3.9/3.12 版本矩阵。

### Fixed（哈希必须对行尾免疫）

两处按**原始字节**做内容哈希，都会在 CRLF/LF 之间误判：

- `engine/.engine-manifest.json`（本次新增）——本机 CRLF、新克隆 LF 会让每个贡献者的
  引擎自检全线失败；
- `audit.content_tree_hash`（既有）——换机器或重新 checkout 导致的行尾变化会被判成
  "内容变了"，**发布路径以"内容哈希不一致，请重跑审计"拦住一次语义上毫无变化的提交**。

统一走新增的 `context.sha256_file()`（行尾先归一为 LF 再哈希）；
`tests/test_repo_invariants.py` 有专门用例断言 LF 与 CRLF 得到同一哈希。

> **升级影响（一次性）**：`content_tree_hash` 换了算法，因此**升级前存下的审计记录
> 第一次会被判成"内容哈希不一致"**——这是预期的，重跑一次 `/kb-audit` 即可。
> 之后它就能在 CRLF/LF 之间稳定了。

### Fixed（CI：windows job 的中文输出把 job 打红）

CI 的 windows 那条腿红在**输出编码**，不是启动器：

```
UnicodeEncodeError: 'charmap' codec can't encode characters in position 5-13
  File "...\cp1252.py", line 19, in encode
  print("hook 启动器在本机可用。")
```

Windows 运行器把 stdout 重定向后用的是 **cp1252**，编不出中文；`adapt_hooks.py --check`
的进度行直接把命令打挂。交互式控制台走 PEP 528 的宽字符 API 不受影响，所以这个坑
**只在 CI / 管道 / 重定向时出现**——本机怎么跑都是绿的（这也是它漏过本机验证的原因）。

- `tools/{adapt_hooks,reinstall,wrap_marketplace}.py` 启动时把 stdout/stderr 重配成 UTF-8
  （`errors="replace"`）。
- 新增回归用例 `ToolOutputEncodingTests`：用 `PYTHONIOENCODING=cp1252` 真跑一次
  `adapt_hooks.py --check`。
- 顺带：`adapt_hooks.py` 的启动器选择改为按**真实可执行性**探测（`py -3` / `python3` /
  `python` 各起一个子进程试），不再按 OS 名假定——Windows 上 `python3` 可能是
  Microsoft Store 占位程序，`shutil.which` 会误判为可用。

### Fixed（跨插件同步不再静默丢失）

两个 README 都写着"本插件是 data-development-plugin 的上游"，实现也在
（`sync._update_data_dev_index` 往 `<consumer>/.data-dev/mock/kb/index.json` 写新表文档），
**但这条链一个测试都没有**——ddp 的测试全是手写的 mock URI 字符串，从来没真接过一次
本插件的产物。

补测试时先发现了一个真 bug：`index.json` 不存在时 `_update_data_dev_index` 返回
`{"ok": False, ...}`，而 **publish 把这个返回值直接丢掉了**。实测：消费方还没初始化时，

```
publish rc = 0，输出里 ok: true，一个字都没提 consumer，consumer 索引也没被创建
```

也就是"kb 先发布、ddp 后初始化"这个顺序下，跨插件同步**一行都没做，而且没人知道**。

- `sync.publish` 的返回值新增 `consumer_sync`（未配置消费方时为 `null`），失败时带上
  reason；同时写一条 `consumer-sync` 到 hook 日志。**不判失败、不回滚**——git 与 OV
  确实成功了，为此回滚只会制造第二个 commit；但它必须可见。
- `commands/publish.md` 写明前置条件（消费方索引必须已存在）与"看到 `ok:false` 要怎么办"。
- 新增 `tests/test_engine.py::ConsumerContractTests`（4 个用例）：写出的文档形状、
  重复发布幂等、缺索引时必须上报、未配置消费方时为 null。
- 消费端的对应断言在 data-development-plugin 的 `tests/test_kb_contract.py`——两边各自
  对着同一份 schema 断言，两个单仓 CI 都能钉住这条跨仓库的缝。
- 另做了一次**真跨插件端到端**（两侧各起进程、通过文件系统交接）：本插件发布后，
  数开侧确实搜到了 `viking://resources/domains/user/tables/ads_user_act_di.md`。

### Fixed（/kb-setup 报成功，但版本控制层可能是死的）

`context._git_init` 完全忽略 `git()` 的返回值：git 不存在时 `/kb-setup` 照样报成功，
用户以为知识库已经版本化了，实际要到发布阶段才会被 `git_commit` 门拦下。

- `_git_init` 返回 git 的真实结果；新增 `context.vcs_status()`；
  `/kb-setup` 的结果里带 `vcs`，`ok:false` 时带上原因与影响。**不硬失败**——
  纯 mock 体验不需要 git，但这件事必须在安装期说出来。
- `commands/setup.md` 要求把 `vcs` 的结果原样告诉用户，而不是只说"初始化完成"。
- 提交身份改由 `git_commit` 用 `-c` 传入，不再写进仓库配置——`/kb-setup` 每次都要跑这一步，
  少两次子进程。
- 新增 `VcsStatusTests`（3 条）：可用 / 配置关闭 / git 缺失时给出原因。

### Fixed（SECURITY.md 的"已知边界"已经过期，报告渠道是死的）

写 `tests/test_known_limits.py` 时把文档里的声明逐条跑了一遍：

- **报告渠道指向空气**：原文让人"联系 marketplace 元数据里的邮箱"，而两个清单里根本没有
  邮箱字段。改为指向 GitHub 的 **Report a vulnerability**，并给了替代路径；维护者须知
  里写清要在 Settings → Security 里开启。
- **已知边界清单过期**：四条"可绕过"实测三条早就拦住了。重写成准确版本，并新增
  `tests/test_known_limits.py`：已拦住的当回归保护（**含 `rules/` 直改的铁律**），
  唯一还开着的（把写操作放进脚本文件）当"已知上限"钉住。

### Fixed（署名 + 英文门面 + 引擎编码）

- 删掉 `.claude-plugin/plugin.json` 里空的 `author.email`；新增不变量断言：署名三处一致，
  且 `email` 要么填真值要么不存在。
- `README.en.md` 改成双宿主，补安装三条（含 macOS/Linux 必须跑 `adapt_hooks.py`），
  写明本插件是 data-development-plugin 的上游、两边契约测试各在哪。
- `py -3 engine/kbp.py --help` 在 cp1252 下直接 UnicodeEncodeError（实测）——引擎启动时
  把 stdout/stderr 重配成 UTF-8。

### Tests

- 新增 `tests/test_repo_invariants.py`（7 个用例）：版本号三方一致、README 的下限必须是
  CI 真跑过的版本、全部源码能用下限语法解析、引擎清单与 engine/ 一致、哈希对行尾免疫。
- 新增 `tests/test_generated_surface.py`（3 个）、`tests/test_hook_wiring.py`（3 个）、
  `CliInvocationTests`（3 个）。全部**只读不写**——写成"跑生成器再比对"会自己把漂移修好。

## [1.2.2] — 2026-09-14

### Added（双宿主：Codex）

- **同一个插件现在也能在 Codex 里跑**，做法与 data-development-plugin 一致：
  - `.codex-plugin/plugin.json`（Codex 清单）+ `hooks/claude-codex-hooks.json`
    （两宿主共用 hook 配置；Codex 与 Claude Code 共用 `PreToolUse` / `PostToolUse` /
    `SessionStart` 契约与 `CLAUDE_PLUGIN_ROOT` 注入）。
  - `skills/kbp-*`：Codex 没有斜杠命令，用户入口是技能；用 `kbp-` 前缀避免与已有的
    `kb-publish` / `kb-audit` 方法论技能撞名（`/kb-setup` → `kbp-setup` …）。
  - `tools/build_codex_surface.py`：从 `commands/*.md` 生成 Codex 面，生成物带「请勿手改」抬头。
  - `engine/templates/AGENTS.kb.md`：Codex 读 `AGENTS.md`，`kb-setup` 按宿主
    （`PLUGIN_DATA` 存在即 Codex）注入对应文件名，Codex 跳过 `.claude/settings.json`。
- `tools/adapt_hooks.py` 现在同时适配 `hooks/hooks.json` 与 `hooks/claude-codex-hooks.json`。
- 安装方式（本机个人 marketplace）：`codex plugin add knowledge-base-plugin@personal`。

## [1.2.1] — 2026-09-14

### Fixed（对抗式验收 v2：路径归一化与载荷形状）

- **Windows 尾随点/空格归一化**：文件系统把 `runtime.` 当 `runtime`、`_state.json.` 当
  `_state.json`，所以 `.kb/runtime. /_state.json.` 这类等价写法能绕过
  `runtime_guard` / `state_write_guard` / `audit_manifest_guard` / `rules_direct_write_guard`。
  现在每个路径分量都做 `rstrip(" .")` 归一化后再比较。
- **载荷形状兜底**：工具名缺失/没见过、或 `tool_input` 不是对象时，具名分支取不到路径会放行。
  现在加了形状兜底（有"写文件/跑命令"的形状就过门；形状异常又提到机器资产时保守拦截）。
- 新增 3 个回归用例（尾随点/空格变体、shell 写文件变体、形状兜底），
  单测 33 → **36**；对抗脚本 v2 **34/34**、v1 **55/55**。
- **关键词误判改为按段匹配**：原先"整条命令里同时出现写动词与 `.kb` 机器资产路径"就拦，
  跨行分析脚本会被误伤；现在按 `;` / `&&` / `||` / 换行切段，要求两者**同段**才判违规。
  单测 36 → **37**。
- **补两条漏网规则**（按段匹配引入的回归）：① 变量展开——`$t = ...\.kb\runtime\x` 与
  `Set-Content -Path $t` 分属两段时，展开后仍按同段判断；② `cd .kb/runtime` 之后的
  相对路径写入一律拦截。单测 37 → **38**。
- **Docs**：`SECURITY.md` 增补「Security model」与「Known limits / non-goals」——
  三层防线强度不同（hook 提高成本、引擎内门控绕不开、审计留证 + 内容哈希是真证据），
  并列出边界（启发式判定、宿主看不到的子进程副作用、APPLIED≠REVIEWED 治理窗口、不是沙箱/RBAC）。

### Fixed（开源前对抗式验收：第一性原理逐条证伪）

用一套 55 条的对抗脚本（路径变形 / 工具变形 / shell 变形 / 证据伪造）打门控，
起初 **40/56**，封堵后 **55/55**。三类根因：

- **路径没归一化（5 处绕过）**：`decide_file_write` 现在 `strip()` + `resolve()`
  （`. `/`..`/软链接/junction 一并归一）并对文件名 `lower()`；
  此前尾随空格（`.kb/_state.json `）与大写文件名（`.KB/.KB-MANIFEST.JSON`）可绕过
  state/审计留证规则，指向 `.kb/runtime` 的 junction 也能绕过。
- **shell 写文件动词表不全（10 处绕过）**：只认 `rm/mv/write_text` 一类，
  漏了 `Set-Content` / `Out-File` / `New-Item` / `cp` / `tee` / `sed -i` 与重定向 `>` `>>`；
  补齐后这些写法一律 BLOCK，只读命令（`Get-Content` / `Test-Path` / `cat`）保持 ALLOW。
- **shell 直改 `rules/` 无规则（2 处绕过）**：新增 `rules_direct_write_guard` 的 CLI 分支，
  与文件写入规则一致（沉淀铁律：必走 propose → 门禁 → Owner approve）。
- **Codex 工具名**：`decide_pre_tool` 现在同时认 `apply_patch` / `exec_command` /
  `local_shell` / `shell_command`，并按补丁段落抽取目标路径（含 `*** Move to:`）。

### Changed

- **hook 层与宿主契约对齐**：输出严格贴宿主 schema（`additionalProperties:false`，
  多写字段会被宿主整条忽略并静默放行）、改用 exit 0 + JSON 决策（exit 2 是"原因写 stderr"的旧协议）、
  超时 15s→60s（慢机器上"python 启动 + 导入引擎"实测约 20s，超时即 fail-open）、
  不相关工具走快速通道不再导入引擎、新增 `DDP_HOOK_TRACE` 原始 payload 追踪。
- 元数据对齐：版本 `1.1.0` → `1.2.0`（与 CHANGELOG 一致）、LICENSE 与 author 改为
  `AI实战技能圈`、README 测试数 `16` → `33`（实际 33 个单测全绿）。

## [1.2.0] — 2026-09-10

### Added
- Real OpenViking HTTP transport (`engine/core/ov_remote.py`): parent-dir
  creation (`/api/v1/fs/mkdir`) + file write (`/api/v1/content/write`,
  `create`/`replace`, waits for semantic/vector processing) + read-back
  verification (`/api/v1/content/read`). Pure stdlib, no new dependencies.
- `ov.remote_enabled=true` now actually publishes to a configured OpenViking
  server; `ov.url` / `ov.api_key_env` (default `OV_API_KEY`) / optional
  `ov.api_key_file` / `ov.account` / `ov.user` config keys added.
- Remote sync failure blocks publish (`gate=ov_remote_sync`), writes no
  manifest entry, and never reports fake success. Manifest/sync-state record
  `remote.server`, `pushed`, `verified` counts.
- `kbp ov-check` diagnostic verb (read-only connectivity + auth check).
- `ov.scope_readme` (default `false`): when publishing to a shared
  `viking://resources/` scope, the repo-level README is kept out of the remote
  push so it cannot clobber a root document owned by another knowledge project.
- 12 unit tests for URI mapping, config resolution, push success/failure, and
  remote publish wiring (33 total).

### Changed
- `.kb/config.json` `ov` section schema extended (backwards compatible: all new
  keys optional, defaults keep local-mirror behavior).

## [1.1.0] — 2026-09-10

### Added
- Generic domain defaults (`user`) and configurable publish root
  (`viking://resources/`) with no vendor namespace.
- Open-source hygiene docs (contributing/security/english readme/CI).
- Audit `content_hash` anchor; publish gate compares current tree hash.
- Machine-file protections for `.kb/_state.json`, `.kb/runtime/**`, audit and
  manifest files (Write + Bash mutation guard).
- Honest `ov_sync` states (`local-mirror` vs `remote`); live publish is refused
  until a remote sync provider is enabled.
- `uri_root` is honored end-to-end (local mirror + data-dev consumer index).

### Changed
- Removed provenance references and internal naming from docs and samples.

### Fixed
- Defaults no longer bind to a single organization namespace.
