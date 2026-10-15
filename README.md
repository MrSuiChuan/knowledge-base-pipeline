# knowledge-base-plugin

把数仓知识从**隐性、分散、易腐烂**，炼成**版本化、可审计、可被 Agent 确定性消费**的结构化事实。
一个插件，两个宿主（Claude Code 与 Codex），共用同一套引擎与 hook。

```text
采集 → 结构化 → 质检 → 审阅 → 发布 → 反哺 → 沉淀
```

Apache-2.0 · Python 3.9+ · mock 模式开箱即用

**第一次来，按你想干的事挑一条路**

| 我想…… | 从这里开始 |
| --- | --- |
| 先看它跑不跑得通 | [快速开始](#快速开始)，一条 demo 命令 |
| 真的用起来 | [安装](#安装)，然后看 [日常命令](#日常命令) |
| 弄懂它为什么这么设计 | [七个环节](#七个环节) 与 [docs/README.md](docs/README.md) |
| 改代码 | [CONTRIBUTING.md](CONTRIBUTING.md) |

## 它解决什么问题

数据团队里天天发生、又没人愿意管的两件事。

**知识散在人身上。** 哪张表谁维护、什么时候能拿数、这个口径为什么这么定，答案散在聊天记录、
老同事的脑子里、三年前的评审文档里。人一走，知识跟着走。

**会话里说过的规矩，说完就丢。** 我偏好什么风格、上次定的那个口径叫什么，AI 下一轮就忘了。

这两件事看起来都叫"知识管理"，落点其实完全不同，插件把它们接成两条链路。

| | 写什么 | 落在哪 | 靠什么触发 |
| --- | --- | --- | --- |
| **知识** | 定稿的表文档 / 规则 / 索引 | `viking://resources/...` | 发布（`/kb-publish`） |
| **记忆** | 这次会话里发生的对话 | `user/<id>/memories`、`agent/<id>/memories` | 提交（`memory commit`） |

第二条链路有个常见误会值得先说清楚。官方文档写着能记会话记忆，装完却看到 0 条，
通常不是坏了，是这条链路从来没人走过。排查过程与真跑记录见
[docs/session-memory.md](docs/session-memory.md)。

## 七个环节

每个环节拧住一个互相打架的矛盾侧面。

| 环节 | 矛盾 | 怎么拧 |
| --- | --- | --- |
| 采集 | 隐性→显性 且不臆造 | 三条路：mock 元数据 / 平台 MCP 6 类元数据 / **主流实时组件直采**（注册表 + 采集器），产物都是带时间锚点的 metadata-snapshot |
| 结构化 | 散点→可推理骨架 | 5 步业务骨架 + 场景锚点表 + 推理纪律 |
| 质检 | 口径不冲突、不断链 | conflict / link（v41 六层）/ index 三检 |
| 审阅 | 质量有人负责 | Owner 终签；APPLIED≠REVIEWED 的窗口要收口 |
| 发布 | 版本化 + 可发现 | git 入库 + OpenViking 双轨 + guard 门控 |
| 反哺 | 保持新鲜 | 元数据漂移比对 → 回灌基础身份 / 字段语义 |
| 沉淀 | 从衰减→生长 | 提案五道门禁 + approve，不手改 `rules/` |

三个闭环：

- **生成闭环**：采集 → 结构化 → 质检 → 审阅 → 发布；
- **消费闭环**：`viking://resources/` 被 data-development-plugin 的 SDS 找表与下游测试消费；
- **反哺闭环**：元数据漂移反向拽新知识（`/kb-refresh`），实战沉淀正向养厚知识（`/kb-propose`）。

本插件是两个开发插件（离线 data-development-plugin、实时 realtime-data-plugin）的**上游**：
发布到 `viking://resources/`，两侧的消费端都只消费该前缀。
`/kb-publish --consumer-root <开发插件项目根>` 可在 mock 模式下把新表文档直接同步进它的知识索引
（`.data-dev/mock/kb/index.json` 或 `.rtd/mock/kb/index.json`，按已存在的那个写入）。

## 快速开始

### 装之前要有什么

- **Python 3.9+**。CI 在 **3.9 与 3.12** 两端跑全量用例，`tests/test_repo_invariants.py`
  会核对这里的声明与 CI 矩阵一致，改下限必须两边一起改；
- **一个宿主**，Claude Code 或 Codex。hook 层两者通用（`PreToolUse` / `PostToolUse` / `SessionStart`）；
- **mock 模式开箱即用**。要接真实数据再补：平台元数据 MCP CLI（live 模式）、git remote（可选）、
  OpenViking 服务（真实发布；`py -3 engine/kbp.py ov-check` 自检连通与鉴权）。

### 安装

本仓库本身是合法插件目录（`claude plugin validate` 通过）。Claude Code 侧推荐包成 marketplace：

```bash
python tools/wrap_marketplace.py <目标仓库根>
claude plugin marketplace add <目标仓库根>
claude plugin install knowledge-base-plugin
```

Codex 侧先生成 Codex 面，再装进本机个人 marketplace：

```bash
py -3 tools/build_codex_surface.py                        # 从 commands/ 生成
codex plugin add knowledge-base-plugin@personal
```

### 装完必须做的一件事

macOS / Linux 上，hook 命令里写的是 Windows 启动器 `py -3`，装完必须跑一次适配：

```bash
python3 tools/adapt_hooks.py          # 把两份 hooks 文件切到本机可用的解释器
python3 tools/adapt_hooks.py --check  # 体检：返回非零就是"装好了但没生效"
```

不做会怎样。hook 命令直接失败，而**宿主把 hook 失败当成放行**，审计门与发布门会全部静默失效。
你以为有门，其实门早就拆了。

### 三条命令看它跑起来

```bash
# 1) 端到端 demo：采集→生成→审计→提案→Owner 终签→发布 v1→元数据漂移→反哺→复审→发布 v2
python engine/kbp.py demo --domain user

# 2) 单测
python -m unittest discover -s tests

# 3) 改了代码，跑一遍与 CI 等价的检查（单测 + compileall + 开源标准 + 两条脱敏扫描 + hook 接线）
py -3 tools/ci_check.py --py-floor
```

## 日常命令

Claude Code 是斜杠命令，Codex 用同名技能（前缀 `kbp-`，对应引擎 `kbp.py`）。下表写 Claude Code 侧的名字。

| 命令 | 干什么 |
| --- | --- |
| `/kb-setup` | 初始化 `.kb`、同步引擎、把规范注入 `CLAUDE.md` / `AGENTS.md` |
| `/kb-generate <domain>` | 5 步业务骨架交互，产出 navigation 加九章节表级文档 |
| `/kb-audit` | 冲突 / 六层链接 / 索引三检；strict 加 publish 时任一 FAIL 不放行 |
| `/kb-propose <一条长期事实>` | 规则提案过五道门禁，产出 APPLIED 待审 |
| `/kb-review` | Owner 终签，待审提案转 active |
| `/kb-publish --reason "知识库 v1"` | git 入库加 OpenViking 双轨发布，由 `kb_publish_guard` 把关 |
| `/kb-refresh <domain>` | 元数据漂移比对，回灌基础身份与字段语义两节 |
| `/kb-remember` | 把这一轮的要点写进会话，收工前提交触发记忆抽取 |
| `/kb-status` / `/kb-overview` | 看当前状态 / 看流水线全貌 |

会话记忆这条链路补一句。会话的建立可以自动（`SessionStart` hook 会建好，失败也不影响你干活），
但**对话内容得显式追加**，因为插件拿不到会话结束事件，也拿不到全量对话。收工前记一次再提交，
才会真的产生记忆；不提交，它就一直是草稿。细节见 [docs/session-memory.md](docs/session-memory.md)。

## 双宿主对应关系

| Claude Code | Codex |
| --- | --- |
| `/kb-setup` | `kbp-setup`（注入 `AGENTS.md` 而不是 `CLAUDE.md`） |
| `/kb-generate user` | `kbp-generate` |
| `/kb-audit`、`/kb-review`、`/kb-propose` | `kbp-audit`、`kbp-review`、`kbp-propose` |
| `/kb-publish`、`/kb-refresh`、`/kb-status`、`/kb-overview`、`/kb-remember` | `kbp-publish`、`kbp-refresh`、`kbp-status`、`kbp-overview`、`kbp-remember` |

三点差异：

- **hook 层通用**。Codex 同样支持三个 hook 事件与 `hookSpecificOutput.permissionDecision`，
  同样注入 `CLAUDE_PLUGIN_ROOT`，所以发布门 / 审计完成度门 / 规则直改拦截照常生效。
  首次在 Codex 里使用需在应用内授权一次 hook 信任；
- **子代理**。Claude Code 的 `Task` 在 Codex 是 `spawn_agent`，`AskUserQuestion` 改成对话里直接问；
- **解释器**。hook 命令默认 `py -3`（Windows），macOS/Linux 跑一次 `adapt_hooks.py` 切换。

`commands/*.md` 是流程的唯一来源；`skills/kbp-*` 与 `.codex-plugin/plugin.json` 都是生成物，不要手改。

## 仓库结构

```text
commands/                     /kb-* 流程定义（Claude Code 侧入口）
skills/                       方法论技能 + kbp-*（Codex 入口技能，生成物）
hooks/                        hooks.json（Claude Code）+ claude-codex-hooks.json（两宿主共用）
                              PreToolUse：发布门 + 审计完成度 + 规则直改拦截
engine/                       kbp.py + core/{context,snapshot,sources,skeleton,render,audit,proposals,sync,gates}.py
                              sources/registry.json（实时组件注册表：谁能采、怎么采、验证到哪一层）
tests/                        unittest 单测与端到端
tools/                        ci_check / publish_public / reinstall / build_codex_surface / validate_oss
docs/                         ARCHITECTURE / session-memory / realtime-sources / release-process / apache-readiness-audit
.claude-plugin/plugin.json    Claude Code 清单（版本号的唯一来源）
.codex-plugin/plugin.json     Codex 清单（生成物，含 +codex.<token> cachebuster）
```

### 改完插件代码，怎么让宿主加载新版本

**不换版本号，你改的东西一行都不会生效。** Codex 把插件按版本号缓存到
`<codex-home>/plugins/cache/<marketplace>/<plugin>/<version>/`，版本号不变就不会重新拷贝。

```bash
py -3 tools/reinstall.py            # 预演：体检 + 打印将要执行的动作
py -3 tools/reinstall.py --apply    # 换 cachebuster + codex plugin add 重装
```

装完**新开一个线程**再用。重装本身不会让 hook 信任失效，只有改动 `hooks/*.json` 才需要重新授权一次。

## 文档地图

不知道读哪份，从 [docs/README.md](docs/README.md) 进，它按"你手上是什么问题"组织。

常读的几份：设计与连接器契约 [docs/REPRODUCTION-NOTES.md](docs/REPRODUCTION-NOTES.md)；
架构与门控 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)；术语 [docs/glossary.md](docs/glossary.md)；
实时组件知识源（注册表 / 采集器 / 本地实验环境 / 真跑记录）
[docs/realtime-sources.md](docs/realtime-sources.md)；会话记忆（为什么没有、怎么开）
[docs/session-memory.md](docs/session-memory.md)。

## 已知边界

这些是**明确做不到或还没验过**的事，写在这里省得你踩：

- **会话内容捕获靠命令驱动，不是自动嗅探**。插件拿不到会话结束事件，也拿不到全量对话，
  所以内容要显式 `memory add` / `memory batch`。把这一步包装成"自动"是做不到的；
- **`memory commit` 会花钱**，抽取要调模型。开关默认关闭，不开就不会有任何调用；
- **实时组件分三层，不要一律当成支持**。Kafka / StarRocks / ClickHouse 是本机真跑过的；
  Doris 采集器已实现但**未验证**；Pulsar / Flink 只登记了角色与连接形状，调它会报
  `collector_not_implemented`；
- **`rules/` 不许手改**，长期事实走提案与 Owner 终签，hook 会直接拦直改；
- **hook 失败会被宿主当放行**，所以非 Windows 装完必须跑一次 `adapt_hooks.py`。

更完整的 Known limits 见 [SECURITY.md](SECURITY.md) 与 [docs/glossary.md](docs/glossary.md) 末尾的"常见误解"。

一条本项目的习惯：**"未验证"是结论，不是客气话**。文档里写"未验证"的地方就是真的没有证据，
欢迎直接按这个去核对。

## 参与与支持

- **遇到问题**：先看 [SUPPORT.md](SUPPORT.md)（按"你手上是什么问题"给文档索引）；提问用 issue 模板，
  带上命令、完整输出、环境、最小复现；
- **想改代码**：[CONTRIBUTING.md](CONTRIBUTING.md)（本仓库特有的坑：改 `engine/` 要重算清单、
  改 `commands/` 要重生成 Codex 面、非 Windows 装完必须跑 `adapt_hooks`）；
- **谁能合并、谁能发版**：[GOVERNANCE.md](GOVERNANCE.md)；**怎么发版**：[docs/release-process.md](docs/release-process.md)；
- **行为要求**：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)；**安全报告**走 [SECURITY.md](SECURITY.md)，
  **不要**开公开 issue；
- **本仓库包含哪些第三方内容**：[docs/third-party-dependencies.md](docs/third-party-dependencies.md) 与 [NOTICE](NOTICE)；
  **开源就绪验收结论**：[docs/apache-readiness-audit.md](docs/apache-readiness-audit.md)。

## License

Apache-2.0 — 见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。

## 公开镜像与私有主干

本仓库有两个面：**私有主干**（日常开发，含内网地址与账号细节）与**公开镜像**
`MrSuiChuan/knowledge-base-pipeline`。镜像由
`py -3 tools/publish_public.py --apply` 从当前提交生成——内容一致，只有脱敏替换：
内网地址 → `<openviking-host>`、主机名 → `<host>`、账号 → `<user>`/`<account>`、
密钥文件路径 → `<key-file>`、本机工作区 → `<workspace>`。

所以你在公开仓库里看到 `<openviking-host>` 这类占位符是**故意的**，不是写坏了；
`--check` 会做替换统计与残留检查（CI 那行"禁止出现的词"列表是唯一豁免）。
同步细节见 [docs/release-process.md](docs/release-process.md) 第 7 节。
