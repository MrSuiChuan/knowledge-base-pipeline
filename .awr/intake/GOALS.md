# 数仓知识库生成流水线插件 {#kb-pipeline status=active}

把隐性、分散、易腐烂的数仓知识，炼成版本化、可审计、可被 Agent 确定性消费的结构化事实。
七环节流水线——采集 → 结构化 → 质检 → 审阅 → 发布 → 反哺 → 沉淀——每个环节都带机器门控
与留证：审计不过不许发布，规则只能走提案，机器资产禁止手改。

来源与依据（这是来源声明，不是验收结论）：

- `README.md` 开头自述与"七个环节"表；
- `.codex-plugin/plugin.json` / `.claude-plugin/plugin.json` 的 description；
- 用户 2026-09-20 指示："继续使用AWR接管一下记忆插件，看看有哪些可以优化的地方"。
  **口径说明**：本机不存在名为"记忆插件"的仓库，插件源仓库只有 knowledge-base-plugin
  与 data-development-plugin 两个。本条按 knowledge-base-plugin 理解（它是这个生态里
  充当知识/记忆层的那一个），已在回复中向用户说明并请其纠正。

当前实现是否满足这个目标，由各工作项的 acceptance 逐条核验；在核验通过前不视为已达成。

# 让插件真正记录会话记忆（OpenViking session → commit → 记忆抽取） {#session-memory status=active}

用户 2026-10-11 的问题："知识库插件为什么没有记录下来会话记忆，OpenViking 官网显示可以的"。

**诊断结论（证据见 KBP-038）**：本插件对 OpenViking 只用了**文件接口**
（`/api/v1/fs/stat`、`/fs/mkdir`、`/content/write|read|download`），写入作用域只有一个——
`viking://resources/`，也就是"已定稿的知识成品"。而 OpenViking 的记忆是另一条链路：
**会话（session）→ 追加消息 → commit → 后台抽取记忆**，落在 `user/<id>/memories/{entities,events,preferences,…}`
与 `agent/<id>/memories/experiences`。这条链路本插件从来没调过，所以"没有会话记忆"不是故障，是**没接**。

本目标把这条链路接上：会话建立/追加/提交/回读 + 记忆抽取任务轮询 + 留证，
并按本仓库的纪律如实标注边界（宿主只给三个 hook 事件，拿不到全量对话，因此捕获只能是
命令驱动而不是自动嗅探）。

来源与依据（这是来源声明，不是验收结论）：

- 用户 2026-10-11 指示："创建台账，创建goal，实现这个完整功能"；
- OpenViking 官方概念第 5 条（Automatic Session Management）："At the end of each session,
  developers can actively trigger the memory extraction mechanism."（本机工作区里导入的官方 README）；
- 服务端路由实证：`/api/v1/sessions`（create / messages / commit / extract / used）、
  `GET /api/v1/tasks/{task_id}`、`POST /api/v1/search/find`（本机已安装包 `openviking 0.3.24` 的路由定义）；
- 本机工作区实证：`session/<uuid>/messages.jsonl`、`user/default/memories/{entities,events,preferences}`、
  `agent/web-playground/memories/experiences`，以及会话 `.meta.json` 里的
  `memories_extracted {profile,preferences,entities,events,cases,patterns,tools,skills}`。

当前实现是否满足这个目标，由各工作项的 acceptance 逐条核验；在核验通过前不视为已达成。

# ClickHouse 采集器与 1.3.0 发版 {#v130 status=active}

两件事，都是用户 2026-10-07 直接指定的：

1. **接 ClickHouse 采集器**：采集层现在缺的三家里（ClickHouse / Pulsar / Flink）先补最像"表"的那一家。
   ClickHouse 与 Doris/StarRocks 同属服务层，但客户端、系统表、输出转义都不一样——
   照搬 MySQL 那套会在"保留字列名"和"TabSeparated 转义"上翻车。
2. **发 1.3.0**：`CHANGELOG` 的 `[Unreleased]` 已经攒了四块大改动（实时组件知识源、
   服务层真跑、详细测试、开源就绪），版本却还停在 1.2.2。发版按 `docs/release-process.md` 走。

同一条指令里还有一项跨仓库工作（把 data-development-plugin 与 realtime-data-plugin 的开源标准
补齐到与本仓库同一口径），记在 KBP-037；它改的是另外两个仓库，**不进它们的 `.awr`**
（那两个仓库各自的台账由别的会话维护，并发写同一份台账会互相踩）。

来源与依据：用户 2026-10-07 指示（本条）；`engine/sources/registry.json` 里 oss_clickhouse 原为 tier 3；
`CHANGELOG.md` 的 `[Unreleased]` 与 `.claude-plugin/plugin.json` 的 1.2.2。

当前实现是否满足这个目标，由各工作项的 acceptance 逐条核验；在核验通过前不视为已达成。

# 按 Apache 项目标准做出可开源的就绪状态 {#apache-readiness status=active}

仓库要对外开源，就得经得起陌生人按"一个正经开源项目"的眼光审。本目标按 **Apache 项目
（ASF 风格）的通行标准**做一次全面排查与优化，四个维度：

* **法律与许可**：LICENSE / NOTICE / 逐文件许可头 / 清单字段 / 第三方与商标边界，且互相不矛盾；
* **流程完整性**：治理（谁能合并、谁能发版）、行为准则、发版清单、贡献入口、安全报告路径；
* **合理性**：流程要能落地，不写"看起来合规但没人会照做"的摆设文件；
* **友好性**：新人能在几分钟内跑起来，文档有索引，模板问的是真需要的信息。

同一套标准已经在相邻插件 realtime-data-plugin 上做过一轮（`docs/apache-readiness-audit.md`，四维度 35 条），
本目标按同一把尺子做，不做第二套口径。

来源与依据（这是来源声明，不是验收结论）：

- 用户 2026-10-07 指示："我要开源，需要安装apache的标准进行处理验收，创建台账，创建goal，开始优化测试"；
- 现状盘点：`LICENSE` 是 MIT（1074 字节）、无 `NOTICE`、无 `CODE_OF_CONDUCT.md` / `GOVERNANCE.md` /
  `SUPPORT.md`，`.github/` 只有 `ci.yml`（无 issue/PR 模板、无 CODEOWNERS）；
- `SECURITY.md` 写的是"仓库目前是私有的"→ 公开前必须改成公开仓库的正确路径；
- 已核对：本仓库全历史无字面密钥（`git log --patch` 扫描只命中一处形如
  `<字段名> = str(settings[...])` 的赋值语句，是从环境变量/密钥文件读取，不是硬编码值）。

当前实现是否满足这个目标，由各工作项的 acceptance 逐条核验；在核验通过前不视为已达成。

# 实时组件知识源：详细测试与收口 {#sources-hardening status=active}

上一轮把实时组件接进了采集层，但"能采"和"经得起细看"是两件事：注册表 / 采集器 / 来源门
只有 13 个用例，命令层的接口（退出码与门控键）没有测试，服务层采集器（Doris / StarRocks 共用的
MySQL 协议采集器）一个用例都没有，更没验证过"组件来源的快照能不能走完后半程"。

本目标把这一层测厚、并收口：每个分支都钉住（含反例）、真链路跑完整（真 Kafka → 快照 → 5 步骨架 →
生成 → 严格审计）、跨插件的组件登记漂移核对一次、全量回归，最后推送远端。

来源与依据（这是来源声明，不是验收结论）：

- 用户 2026-10-07 指示："push，并进行详细测试，创建台账，创建goal"；
- 上一轮留下的缺口：`docs/realtime-sources.md` 第七节"未验证的组件"，以及 KBP-016 仍未真跑；
- 相邻插件 realtime-data-plugin 的 `governance/oss-components.json`（13 个组件）可作登记漂移的对照。

当前实现是否满足这个目标，由各工作项的 acceptance 逐条核验；在核验通过前不视为已达成。

# 实时组件知识源：让采集认主流实时处理组件 {#realtime-sources status=active}

采集这一环现在只有两条路：mock 的 `.kb/mock/meta.json`，和 live 下调平台元数据 MCP
（`config.cli.metadata` 的 `snapshot --domain`）。也就是说"知识从哪来"是写死的，
快照里的 `source` 也写死成 `platform-mcp`。主流实时处理组件——Kafka / Pulsar / Flink /
Doris / StarRocks / ClickHouse——既没有那个 CLI，也没有把它们的元数据接进 6 类知识契约的地方。

本目标把"实时组件"变成一等知识源：**组件注册表**（谁、什么角色、怎么连、能采到什么）+
**采集适配层**（组件元数据 → 6 类知识）+ **snapshot 提供方可插拔** + **未登记来源硬门**，
并在本机真起组件取证。用户 2026-10-07 指示："要兼容目前主流实时处理组件，
可以在本地安装对应的组件，测试的时候启动对应的组件即可"。

来源与依据（这是来源声明，不是验收结论）：

- `engine/core/snapshot.py` 的 `fetch_metadata`：live 只认 `config.cli.metadata`，`source` 硬编码为 `platform-mcp`；
- `docs/ARCHITECTURE.md` 第 3 节"采集契约（snapshot）"；
- 用户 2026-10-07 指示（本条）与同日目标澄清"是记忆插件，openviking的那个"；
- 相邻插件的既有做法可复用：realtime-data-plugin 的 `governance/oss-components.json`（13 个组件已本机真跑）。

当前实现是否满足这个目标，由各工作项的 acceptance 逐条核验；在核验通过前不视为已达成。
