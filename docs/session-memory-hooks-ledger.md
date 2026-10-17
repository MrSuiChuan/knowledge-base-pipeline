# 会话记忆自动捕获改造台账（2026-10-17）

## 一、为什么要改

OpenViking 官方为 Codex 提供了 `openviking-memory` 插件（`examples/codex-memory-plugin`），
把记忆做成**生命周期驱动**的链路：

| Codex 事件 | 官方插件行为 |
| --- | --- |
| `SessionStart`（startup/clear/resume） | 注入 profile、preferences/entities 索引与技能目录 |
| `UserPromptSubmit` | 按当前 prompt 检索并注入相关记忆 |
| `Stop`（每轮回调） | 把本轮新增对话追加进会话（`add_message`） |
| `PreCompact` | 捕获剩余轮次并在压缩前提交 |
| `SessionEnd`（Codex ≥0.145） | 宽限期退出时提交会话 |
| `PreToolUse(Bash)` | 发现 `viking://` URI 时提示改用 MCP 工具 |

来源：<https://docs.openviking.ai/en/agent-integrations/04-codex>、
`examples/codex-memory-plugin/hooks/hooks.json`、`scripts/auto-capture.mjs`、`scripts/auto-recall.mjs`。

本插件此前只声明 `PreToolUse / PostToolUse / SessionStart` 三个事件，且只有 `SessionStart`
会碰记忆（建会话）；对话内容完全依赖人或 Agent 手工 `memory add`，`commit` 也要手工触发。
**所以"实时同步"从未实现，不是服务端坏了。**

历史事实（2026-10-11）：在 `.tmp/live-source/proj-remote` 里用一次性脚本对
`http://<openviking-host>:1933` 跑通过一次 `begin → add×6 → commit`，抽取
`memory_write=3`（留证 `commit-2026-10-11T114543Z.json`）。它证明链路能通，但不具备持续性。

## 二、差距清单与验收

| 编号 | 差距 | 本轮处理 | 验收（机器可验） | 状态 |
| --- | --- | --- | --- | --- |
| KBP-HOOK-001 | 无 `UserPromptSubmit` 召回 | 新增 hook + `memory recall` | 假服务端命中检索请求；hook 输出 `hookSpecificOutput.additionalContext` | ✅ 完成 |
| KBP-HOOK-002 | 无 `Stop` 逐轮捕获 | 新增 hook + `memory capture`（解析 Codex rollout JSONL） | 同一 transcript 跑两次只追加一次（水位去重） | ✅ 完成 |
| KBP-HOOK-003 | 无阈值提交 | `pending_tokens >= commit_token_threshold` 时自动 commit | 假服务端返回 pending 超阈值 → 观察到 commit 调用 | ✅ 完成 |
| KBP-HOOK-004 | 无压缩前提交 | 新增 `PreCompact` hook：捕获剩余 + commit | hook 退出码 0 且调用 commit | ✅ 完成 |
| KBP-HOOK-005 | 无会话结束提交 | 新增 `SessionEnd` hook（本机 Codex 0.135 不触发，保留声明） | hook 单独调用时提交；宿主不支持时不报错 | ✅ 完成 |
| KBP-HOOK-006 | 无崩溃/空闲兜底 | `SessionStart` 扫描空闲会话（TTL 30min）补捕获 + 提交 | 空闲会话在下次 SessionStart 被补提交 | ✅ 完成 |
| KBP-HOOK-007 | 配置与官方不一致 | `ov.url` 为空时回退读 `~/.openviking/ovcli.conf`（url/api_key） | 只配 ovcli.conf 也能 `ov-check` | ✅ 完成 |
| KBP-HOOK-008 | 无自动链路测试 | 假 OV 服务端（stdlib HTTP）+ hook 直调 | `tests/test_memory_hooks.py` 全绿 | ✅ 完成 |

不做（本轮明确不做）：Node 版 stdio MCP 代理、profile/技能目录注入、usage 报表。
这些与"把会话实时写进 OV"不是同一件事，单独立项。

## 三、设计约束

1. **默认仍由 `ov.memory_enabled` 总开关控制**；记忆关着时所有 hook 静默放行（fail-open）。
2. **捕获不阻塞对话**：hook 失败只写 `systemMessage`/debug 日志，绝不改变宿主决策。
3. **去重靠水位**：每个 Codex session 记录已捕获的 turn 数；transcript 变短（`/compact`）时从
   最近的 user turn 续接，不整段重放。
4. **会话 id 采用官方约定** `cx-<codex-session-id>`，与本插件手工会话（UUID）并存。
5. **提交有成本**：只在阈值、压缩前、会话结束、空闲清扫时 commit；不在每一轮 commit。

## 四、验证记录（2026-10-17）

| 项 | 结果 |
| --- | --- |
| `tests/test_memory_hooks.py` | 11 条全绿（transcript 解析、水位去重、阈值提交、关键词模式、召回块、4 个 hook 直调、服务不可达 fail-open、空闲清扫） |
| 全量单测（3.12） | 180 OK |
| 全量单测（3.9，CI 矩阵下限） | 180 OK |
| `tools/ci_check.py --fast` | compileall / OSS 标准 / 两条脱敏扫描 / hook 接线 / 门控回归 全 OK |
| 真实实例联调 | ✅ 已完成（2026-10-17，见第五节）：线上 0.4.11，2 条消息 → 提交 → 抽取 1 条记忆（10,661 tokens）→ 召回命中 |

## 五、线上真跑（2026-10-17）

环境：`http://<openviking-host>:1933`（OpenViking 0.4.11，`auth_mode=api_key`，`/health=200`、`/ready=200`）。
临时项目：`%TEMP%\ov-online-hook-test\proj`（`ov.url` 显式写线上地址，`api_key_file` 指向本机密钥；
阈值调到 10 万，确保是 PreCompact 提交而不是 Stop 自动提交）。

Transcript：user 一条（三条事实：user_id STRING / 活跃定义 / SQL 4 空格）+ 一个 function_call + assistant 一条。

| 步骤 | 结果 |
| --- | --- |
| `hooks/stop.py`（真实 hook，stdin=Codex payload） | 退出码 0，输出 `{}`；服务端会话 `cx-online-hook-10172110`：`message_count=2`、`pending_tokens=82`、`commit_count=0`（function_call 被正确忽略） |
| `hooks/precompact.py`（真实 hook） | 退出码 0，输出 `{}`；`commit_count=1`，约 24 秒后抽取完成 |
| 服务端会话回读 | `memories_extracted.total=1`、`llm_token_usage.total_tokens=10661`、`uri=viking://user/<user>/sessions/cx-online-hook-10172110` |
| 记忆落点 | `viking://user/<user>/memories/preferences/当前用户/代码风格.md`（modTime `2026-10-17T13:11:48Z`），内容含上述三条事实 |
| 召回（新 `memory recall` 路径） | query="SQL 缩进偏好" → 第 1 条命中该文件；同批还有 10-11 的三条旧记忆 |

附带修复：真机联调时发现 `setup_guard` 不认 `--root`——在未初始化目录里对已初始化项目执行
`kbp.py memory recall --root <项目>` 会被误拦。`engine/core/gates.py` 现在会从命令里取
`--root` 解析项目（回归：`tests/test_engine.py::CliInvocationTests::test_root_flag_reaches_an_initialized_project`）。
