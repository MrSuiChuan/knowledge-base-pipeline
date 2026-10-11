# knowledge-base-plugin

数仓知识库生成流水线插件：把“隐性、分散、易腐烂”的数仓知识，炼成**版本化、可审计、
可被 Agent 确定性消费的结构化事实**。

> 独立实现：把"隐性 → 显性 → 版本化 → 可被 Agent 确定性消费"的知识生成工艺
> 做成可安装的 Claude Code 插件。七环节（采集/结构化/质检/审阅/发布/反哺/沉淀）
> 各自带机器门控与留证。

## 七个环节

```text
采集 → 结构化 → 质检 → 审阅 → 发布 → 反哺 → 沉淀
```

每个环节拧住一个互相打架的矛盾侧面：

| 环节 | 矛盾 | 怎么拧 |
| --- | --- | --- |
| 采集 | 隐性→显性 且不臆造 | 三条路：mock 元数据 / 平台 MCP 6 类元数据 / **主流实时组件直采**（注册表 + 采集器），产物都是带时间锚点的 metadata-snapshot |
| 结构化 | 散点→可推理骨架 | 5 步业务骨架 + 场景锚点表 + 推理纪律 |
| 质检 | 口径不冲突、不断链 | conflict/link（v41 六层）/index 三检 |
| 审阅 | 质量有人负责 | Owner 终签；APPLIED≠REVIEWED 窗口要收口 |
| 发布 | 版本化 + 可发现 | git 入库 + OpenViking 双轨 + guard 门控 |
| 反哺 | 保持新鲜 | 元数据漂移比对 → 回灌基础身份/字段语义 |
| 沉淀 | 从衰减→生长 | 提案五道门禁 + approve，不手改 rules/ |

## 与 data-development-plugin 的关系

本插件是 **data-development-plugin 的上游**：发布到 `viking://resources/`，
SDS 阶段只消费该前缀的知识。`/kb-publish --consumer-root <data-dev 项目根>` 可在 mock 模式下
把新表文档直接同步进 data-development-plugin 的 `.data-dev/mock/kb/index.json`。

## 目录结构

```
.claude-plugin/plugin.json
.codex-plugin/plugin.json     Codex 清单（由 tools/build_codex_surface.py 生成）
commands/         /kb-setup /kb-generate /kb-audit /kb-review /kb-propose /kb-publish /kb-refresh /kb-status /kb-overview /kb-remember
skills/           domain-knowledge-generator / disclosure-domain-skill / kb-publish / data-quality-kb-maintain / kb-audit
                  kbp-setup / kbp-generate / …（Codex 入口技能，从 commands/ 生成）
hooks/            hooks.json（Claude Code）+ claude-codex-hooks.json（两宿主共用）
                  PreToolUse：kb_publish_guard + audit_completion_guard + rules 直改拦截
engine/           kbp.py + core/{context,snapshot,sources,skeleton,render,audit,proposals,sync,gates}.py
                  sources/registry.json（实时组件注册表：谁能采、怎么采、验证到哪一层）
                  templates/CLAUDE.kb.md + templates/AGENTS.kb.md + settings.json（kb-setup 注入）
tests/            38 个单测/端到端（unittest）
tools/wrap_marketplace.py
tools/build_codex_surface.py  从 Claude 源生成 Codex 面
docs/             ARCHITECTURE.md / REPRODUCTION-NOTES.md / realtime-sources.md
```

## 快速开始

### 环境

- Claude Code + Python 3.9+（CI 在 **3.9 与 3.12** 两端跑全量用例；下限改了要同步改这里，
  `tests/test_repo_invariants.py` 会核对声明与 CI 矩阵一致）；
- Windows 用 `py -3`（hooks.json 的提交默认值）。**macOS/Linux 装好后必须跑一次
  `python3 tools/adapt_hooks.py`** 把 hook 启动器切成本机可用的那个——不跑的话
  hook 命令直接失败，而**宿主把 hook 失败当成放行**，审计门/发布门会全部静默失效。
  用 `python3 tools/adapt_hooks.py --check` 体检，返回非零就是"装好了但没生效"；
- mock 模式开箱即用；live 模式需 metadata MCP CLI 与（可选）git remote；
  OpenViking 真实发布内置 HTTP 同步器（配置 `ov.url` + `OV_API_KEY`，
  自检命令 `py -3 engine/kbp.py ov-check`）。

### 安装

本仓库本身是合法插件目录（`claude plugin validate` 通过）。推荐包装成 marketplace：

```bash
python tools/wrap_marketplace.py <目标仓库根>
claude plugin marketplace add <目标仓库根>
claude plugin install knowledge-base-plugin
```

### 改完插件代码，怎么让宿主加载新版本

**这一步不做，你改的东西一行都不会生效。** Codex 把插件按版本号缓存到
`<codex-home>/plugins/cache/<marketplace>/<plugin>/<version>/`，版本号不变就不会重新
拷贝——所以改完代码必须换一次 `+codex.<token>` 后缀。

```bash
py -3 tools/reinstall.py            # 预演：体检 + 打印将要执行的动作
py -3 tools/reinstall.py --apply    # 换 cachebuster + codex plugin add 重装
```

脚本依次做四件事，任何一步不满足都会明确报错而不是装作成功：
按 `commands/*.md` 重生成 Codex 面 → 确认 marketplace 条目**指向本仓库**
（Codex 把 `source.path` 解析成相对**用户主目录**的路径，不是相对 `marketplace.json`
所在目录——同一个作者的上一个插件踩过这个坑）→ 换版本为 `<基础版本>+codex.<UTC 时间戳>`
→ `codex plugin add`。

装完**新开一个线程**再用。重装本身不会让 hook 信任失效；只有改动 `hooks/*.json`
的内容才需要重新授权一次。

### 离线验证

```bash
# 端到端 demo：采集→生成→审计→提案→Owner 终签→发布 v1→元数据漂移→反哺→复审→发布 v2
python engine/kbp.py demo --domain user

# 单测
python -m unittest discover -s tests
```

### 在 Claude Code 里使用

```text
/kb-setup                        # 初始化 .kb、同步引擎、注入规范
/kb-generate user                # 5 步骨架交互 -> navigation + 9 章节表文档
/kb-audit                        # strict+publish 质检（不过不许发布）
/kb-propose 描述一条长期事实       # 规则提案 -> 引擎门禁 -> APPLIED/READY_FOR_REVIEW
/kb-review                       # Owner 终签 -> active
/kb-publish --reason "知识库 v1"  # git + OpenViking 双轨发布
/kb-refresh user                 # 元数据漂移回灌（反哺闭环）
/kb-remember                     # 把这一轮的要点写进会话（收工前提交，触发记忆抽取）
/kb-status
```

### 在 Codex 里使用（同一插件，双宿主）

Codex 没有斜杠命令，用户入口是**技能**。为避免与 `kb-publish` / `kb-audit` 两个方法论技能
撞名，Codex 入口技能统一用 `kbp-` 前缀（对应引擎 `kbp.py`）：

```bash
# 1) 生成 Codex 面（.codex-plugin/plugin.json、hooks/claude-codex-hooks.json、
#    skills/kbp-*、engine/templates/AGENTS.kb.md）
py -3 tools/build_codex_surface.py

# 2) 装进 Codex（本机个人 marketplace：~/.agents/plugins/marketplace.json）
codex plugin add knowledge-base-plugin@personal
```

| Claude Code | Codex |
| --- | --- |
| `/kb-setup` | `kbp-setup`（注入 `AGENTS.md` 而不是 `CLAUDE.md`） |
| `/kb-generate user` | `kbp-generate` |
| `/kb-audit`、`/kb-review`、`/kb-propose` | `kbp-audit`、`kbp-review`、`kbp-propose` |
| `/kb-publish`、`/kb-refresh`、`/kb-status`、`/kb-overview`、`/kb-remember` | `kbp-publish`、`kbp-refresh`、`kbp-status`、`kbp-overview`、`kbp-remember` |

差异与注意事项：

- **Hook 层两个宿主通用**：Codex 同样支持 `PreToolUse` / `PostToolUse` / `SessionStart`
  与 `hookSpecificOutput.permissionDecision`，且同样注入 `CLAUDE_PLUGIN_ROOT`，
  所以 `kb_publish_guard` / `audit_completion_guard` / `rules 直改拦截` 照常生效。
  首次在 Codex 里使用需在应用内授权一次 hook 信任。
- **子代理**：Claude Code 的 `Task` 在 Codex 用 `spawn_agent`；
  `AskUserQuestion` 改为对话内直接问。
- **解释器**：hook 命令默认 `py -3`（Windows）；macOS/Linux 跑
  `python3 tools/adapt_hooks.py`，会同时切换两份 hooks 文件。
- 改流程请改 `commands/*.md` 后重跑生成器；`skills/kbp-*` 与 `.codex-plugin/plugin.json`
  都是生成物，不要手改。

## 文档

不知道读哪份就从这里进：[docs/README.md](docs/README.md)（文档地图）。

常读的几份：设计与连接器契约 [docs/REPRODUCTION-NOTES.md](docs/REPRODUCTION-NOTES.md)；
架构与门控 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)；
术语 [docs/glossary.md](docs/glossary.md)；
实时组件知识源（注册表 / 采集器 / 本地实验环境 / 真跑记录）[docs/realtime-sources.md](docs/realtime-sources.md)。

## 参与与支持

- **遇到问题**：先看 [SUPPORT.md](SUPPORT.md)（按"你手上是什么问题"给文档索引）；提问请用 issue 模板，
  带上命令、完整输出、环境、最小复现；
- **想改代码**：读 [CONTRIBUTING.md](CONTRIBUTING.md)（含本仓库特有的坑：
  改 `engine/` 要重算清单、改 `commands/` 要重生成 Codex 面、非 Windows 装完必须跑 `adapt_hooks`）；
- **谁能合并、谁能发版、分歧怎么定**：[GOVERNANCE.md](GOVERNANCE.md)；
  **发版怎么做**：[docs/release-process.md](docs/release-process.md)；
- **行为要求**：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)；
- **安全报告**：走 [SECURITY.md](SECURITY.md)，**不要**开公开 issue；
- **本仓库包含哪些第三方内容**：[docs/third-party-dependencies.md](docs/third-party-dependencies.md) 与 [NOTICE](NOTICE)；
- **开源就绪验收结论**：[docs/apache-readiness-audit.md](docs/apache-readiness-audit.md)。

一条本项目的习惯：**"未验证"是结论，不是客气话**。文档里写"未验证"的地方就是真的没有证据，
欢迎直接按这个去核对。

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
