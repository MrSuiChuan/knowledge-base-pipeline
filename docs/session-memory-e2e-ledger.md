# 会话记忆全流程端到端测试台账（2026-10-17）

## 一、范围与判定

**线上实例**：`http://<openviking-host>:1933`（OpenViking 0.4.11，`auth_mode=api_key`，
`/health=200`、`/ready=200`）。

两套实验台，原始输出逐条落盘：

| 实验台 | 用例数 | 覆盖 |
| --- | --- | --- |
| `kb-e2e-lab` | 20 | 线上连通/鉴权、自动记忆链（Stop/PreCompact/Recall）、失败路径 |
| `ddp-testlab` | 135 | 三个插件的结构、知识流水线、hooks 门控、跨插件契约回归 |

判定：全部步骤满足期望记 PASS；环境受限记 BLOCKED（不算通过）；其余 FAIL 并入缺陷台账。

## 二、kb-e2e-lab：20/20 PASS（161.4 秒）

| 用例 | 覆盖 | 结果 |
| --- | --- | --- |
| E-01 | 线上 `/health` + `/ready` | PASS |
| E-02 | 正确 key=200、错误 key=4xx | PASS |
| E-03 | 不存在会话回读=404 | PASS |
| E-04 | `ov.url` 为空时回退 `ovcli.conf` | PASS |
| A-01 | 临时项目初始化 + 指向线上 | PASS |
| A-02 | Stop 逐轮追加（2 条文本 + 1 个 tool_call → 只收 2 条） | PASS |
| A-03 | 重复 Stop 去重（水位） | PASS |
| A-04 | PreCompact 提交 | PASS |
| A-05 | 抽取完成（memories≥1） | PASS |
| A-06 | 记忆落到 `preferences/当前用户/代码风格.md` | PASS |
| A-07 | 语义召回命中新记忆 | PASS |
| A-08 | UserPromptSubmit 注入 `additionalContext` | PASS |
| A-09 | keyword 模式：无关对话不建会话 | PASS |
| A-10 | transcript 变短后从最近 user 轮续接（total 2→3） | PASS |
| A-11 | pending token 超阈值时 Stop 直接提交 | PASS |
| F-01 | transcript 读不到：`systemMessage` + exit 0 | PASS |
| F-02 | 服务不可达：召回静默 `{}` | PASS |
| F-03 | 错误密钥：静默 `{}` | PASS |
| F-04 | 缺 `transcript_path`：no-op | PASS |
| F-05 | `memory_enabled=false`：两个 hook 都静默 | PASS |

### 关键回执

- 会话：`cx-e2e-1017214048-130cb7`
  - Stop 后：`messages=2`、`pending=71`、`commits=0`
  - PreCompact 后：`commits=1`
  - 抽取：`memories=1`、`llm tokens=10703`
  - 压缩续接后：`total=3`、`pending=24`
- 记忆文件：`viking://user/<user>/memories/preferences/当前用户/代码风格.md`
- 召回：`find "SQL 缩进偏好"` 命中该文件；UserPromptSubmit 返回的
  `additionalContext` 含 `<openviking-memory>` 块。

## 三、ddp-testlab 回归：135/135 PASS（825.6 秒）

覆盖：G 结构 18 / D 离线插件 72 / K 记忆插件 38 / X 跨插件 7。
重点回归项：`setup` 幂等、审计新鲜度、记忆门控优先级、`--root` 门控修复、
知识流水线（采集→生成→审计→提案→终签→发布→反哺）、禁用记忆时的静默行为。

## 四、发现与处理

| 编号 | 现象 | 处理 |
| --- | --- | --- |
| KBP-HOOK-009 | 在未初始化目录里对 `--root` 指向的已初始化项目执行记忆命令，被 `setup_guard` 误拦 | 已修：`engine/core/gates.py` 解析命令里的 `--root`；回归 `CliInvocationTests::test_root_flag_reaches_an_initialized_project`（提交 `4cb33d8`） |
| LAB-001 | 实验台捕获变量按用例隔离，连续流程（A-02→A-04→A-05→A-10）拿不到同一会话 id | 已修：`kb-e2e-lab` 运行器改为同一次运行内共享捕获值 |
| LAB-002 | `cases` 目录被误建为文件，导致用例加载失败 | 已修：重建为目录（仅实验台，不影响插件） |

本轮**没有发现新的插件缺陷**；插件侧 181 条单测（3.9/3.12）与公开镜像 CI 四个 job 全绿。

## 五、证据路径

- 用例文档：`kb-e2e-lab/TEST-CASES.md`（20 条）
- 执行台账：`kb-e2e-lab/LEDGER.md`、`kb-e2e-lab/results.json`
- 逐条原始输出：`kb-e2e-lab/runs/<用例ID>/`
- 回归台账：`ddp-testlab/LEDGER.md`（135 条）
