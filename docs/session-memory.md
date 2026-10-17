# 会话记忆（OpenViking session → commit → 记忆抽取）

## 一、先说清楚：为什么以前"没有记录会话记忆"

本插件对 OpenViking 原先只用**文件接口**（`/api/v1/fs/stat`、`/fs/mkdir`、
`/content/write|read|download`），写入作用域只有一个：`viking://resources/`——
那是**已定稿的知识成品**。

而 OpenViking 的记忆是**另一条链路**：

```
会话（session） → 追加消息 → commit（归档 + 后台抽取记忆） → user/<id>/memories 与 agent/<id>/memories
```

这条链路本插件从来没调过。所以"没有会话记忆"不是故障，是**没接**——
OpenViking 官方的能力一直在，插件没去用它。

两条路的区别，一句话：

| | 写什么 | 落在哪 | 谁触发 |
| --- | --- | --- | --- |
| **知识发布**（原有） | 定稿的表文档 / 规则 / 索引 | `viking://resources/...` | `/kb-publish` |
| **会话记忆**（新增） | 这次会话里发生的对话 | `user/<id>/memories`、`agent/<id>/memories` | `memory commit` |

## 二、怎么用

**前置**：OpenViking 服务得先起着（本机是 `openviking-server` / 官方 CLI 那一套；
2026-10-11 做这轮功能时它是**停着的**，所以只做了桩验证，没做真跑）。服务起来后先用
`py -3 engine/kbp.py ov-check` 确认连通与鉴权。

**密钥**：本机地址（`127.0.0.1` / `localhost` / `::1`）**允许不带 key**——本机 OpenViking 是
dev 模式（服务端 `server/auth.py`："Dev mode: no authentication, always return ROOT"），
`ovcli.conf` 里本来就没有密钥。非本机地址仍然强制要 key（从 `OV_API_KEY` 或
`ov.api_key_file` 读，不落 git）。

先在 `.kb/config.json` 的 `ov` 段打开开关（默认关，因为它会花模型配额）：

```json
{
  "ov": {
    "url": "http://127.0.0.1:1933",
    "api_key_env": "OV_API_KEY",
    "memory_enabled": true,
    "keep_recent_count": 10,
    "task_timeout": 180
  }
}
```

```bash
py -3 engine/kbp.py memory begin                      # 建会话并绑定到本项目（SessionStart 也会自动做）
py -3 engine/kbp.py memory add --role user --content "把口径写清楚"
py -3 engine/kbp.py memory add --role assistant --file /tmp/reply.md
py -3 engine/kbp.py memory batch --json-file messages.json   # {messages:[{role,content},…]}，>100 条自动分批
py -3 engine/kbp.py memory commit                     # 归档 + 触发记忆抽取（默认等到任务终态）
py -3 engine/kbp.py memory commit --no-wait           # 只触发，不等
py -3 engine/kbp.py memory status                     # 回读 message_count / memories_extracted
py -3 engine/kbp.py memory used --uris viking://resources/domains/user/index.md
```

## 三、边界（如实标注，不假装能做到）

**1. 捕获是命令驱动，不是自动嗅探。** 本插件只声明了三个 hook 事件
（`PreToolUse` / `PostToolUse` / `SessionStart`，见 `hooks/hooks.json`），
**拿不到"会话结束"事件，也拿不到全量对话**。所以：

- `SessionStart` 会自动把会话**建好**（fail-open：失败只静默跳过，绝不影响会话启动）；
- 对话内容要靠 Agent / 使用者通过 `memory add`（或 `memory batch`）**显式追加**；
- 想让这一步不靠人记着，用宿主里的一句话提示自己："收工前 `memory commit`"。

把捕获写成"自动"是做不到的，写进文档比做一个假的自动更诚实。

### 日常怎么用（接到线上实例）

装好之后，日常就三件事：

1. **把项目接到你要记的那台实例**（`.kb/config.json`）：

```json
"ov": {
  "url": "http://<openviking-host>:1933",
  "api_key_file": "<本机密钥文件路径，如 <key-file>>",
  "memory_enabled": true
}
```

2. **开场自动建会话**：`SessionStart` hook 会在启用时 `memory begin`（已有会话则复用），
   并在提示里带一句"收工前跑 `memory commit`"。
3. **收工前记一次**：`/kb-remember`（Codex 用 `kbp-remember`）把这一轮的要点写进会话，
   再 `memory commit` 触发抽取——**这一步才会产生记忆**，不 commit 就一直只是会话草稿。

**别连错实例**：两台实例长得像，用三处一眼分辨——

| 判据 | 本机那台 | 线上那台 |
| --- | --- | --- |
| `/health` 的 `version` | 0.3.24 | **0.4.11** |
| `/health` 的 `auth_mode` | `dev`（不鉴权） | **`api_key`** |
| `/health` 的 `account_id`/`user_id` | 无 | **<account> / <user>** |
| `/ready` 的 `checks.embedding` | 余额不足时会失败 | `ok` |

`ov-check` 现在会把这些直接打出来。本机那台（MiniMax、余额 402）**已经停掉**，
如果发现它又被起来并被误连，`ov-check` 会显示 `version=0.3.24 + auth_mode=dev`——
看到这两个就别提交（`commit` 也会以 `memory_not_ready` 拒绝白提交）。

**2. commit 会花钱。** 记忆抽取走使用者在 `ov.conf` 里配的 embedding / vlm 模型
（本机配置是 MiniMax）。所以：

- 默认 `memory_enabled: false`，不开就不会有任何调用；
- `commit` 前想清楚这次会话值不值得抽取；
- `--no-wait` 只触发不轮询，适合"批量补录历史会话"的场景。

**3. 提交与抽取是两件事。**
`commit` = 归档（同步完成）+ 抽取（**后台**任务，返回 `task_id`）。
`memory commit` 默认轮询 `GET /api/v1/tasks/{task_id}` 到终态；超时会如实报
`memory_task_timeout`，**但留证照写**——归档确实发生了，这条事实不能因为没等到抽取就消失。

## 四、留证

| 产物 | 位置 | 说明 |
| --- | --- | --- |
| 会话绑定 | `.kb/runtime/memory/session.json` | `session_id`、首次创建时间、累计追加条数、提交历史 |
| 提交留证 | `.kb/runtime/memory/commit-<ts>.json` | 提交请求结果、`task_id`、任务终态（或超时原因） |

两者都在 `.kb/runtime/` 下，属**机器资产**：只由引擎写，hook 拦手工改。
`memory status` 会把服务端回读的 `message_count` 与 `memories_extracted` 一起打出来——
本地计数与服务端计数对不上时，以服务端为准。

## 五、接口来源（不留白）

本模块用到的路径与字段，取自本机已安装的 `openviking 0.3.24` 服务端路由定义
（`server/routers/sessions.py`、`server/routers/tasks.py`），不是猜的：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/sessions` | 建会话（可自带 `session_id`） |
| POST | `/api/v1/sessions/{id}/messages` | 追加一条（`role` + `content` 或 `parts`） |
| POST | `/api/v1/sessions/{id}/messages/batch` | 批量追加（服务端上限 100 条/次） |
| POST | `/api/v1/sessions/{id}/commit` | 归档 + 后台抽取，返回 `task_id` |
| POST | `/api/v1/sessions/{id}/extract` | 只抽取、不归档 |
| POST | `/api/v1/sessions/{id}/used` | 记录用到了哪些上下文 / 技能 |
| GET | `/api/v1/sessions/{id}` | 回读 `message_count` / `memories_extracted` |
| GET | `/api/v1/tasks/{task_id}` | 轮询后台任务 |

鉴权与密钥来源与发布链路完全一致（`ov.url` + `OV_API_KEY` / `ov.api_key_file`），
不新开第二套读取路径。

## 六、真跑记录（2026-10-11）

> **先分清两套实例**（这一条是踩过误会才写下的）：
>
> | 实例 | 版本 | 鉴权 | 模型 | 状态 |
> | --- | --- | --- | --- | --- |
> | 本机 `127.0.0.1:1933` | 0.3.24 | dev（不鉴权） | **MiniMax**：`embo-01`（1536 维）+ `MiniMax-Text-01` | 归档可用；抽取因账户 402 余额不足而失败 |
> | 线上 `<openviking-host>:1933`（主机 `<host>`） | 0.4.11 | `api_key` | **豆包**：`doubao-embedding-vision-251215`（1024 维）+ `doubao-seed-2-0-lite-260428` | `ready_ok=true`，embedding 健康；但**0 会话 / 0 记忆**——从来没人在这台上建过会话 |
>
> 线上实例的模型清单取自它自己的 `GET /api/v1/observer/models`（返回 VLM/Embedding 两张表，
> 带调用次数、token 用量与最近调用时间），不是猜的。把插件指向线上只要改 `.kb/config.json`：
> `ov.url` 换成线上地址、`ov.api_key_file` 指向本地密钥文件（或设 `OV_API_KEY`）。
> **注意线上是生产实例**：`memory commit` 会写入会话并消耗豆包 token，跑之前先想清楚。
>
> 线上服务端部署（登机核对，只读）：`/etc/systemd/system/openviking.service` →
> `ExecStart=/data/ovenv/bin/openviking-server --host 0.0.0.0 --port 1933 --config /root/.openviking/ov.conf`，
> `WorkingDirectory=/data/openviking`，工作区 `/data/openviking/data`，自 2026-09-09 起常驻。
> 它的 `viking://resources/` 有 266 个文件（`domain` / `domains` / `rules`）——**知识发布在用**，
> 而 `/api/v1/sessions` 为空、`stats/memories` 为 0，说明**会话记忆这条链路在线上从未被走过**。

环境：本机 `openviking-server` 0.3.24，绑 `127.0.0.1:1933`。启动日志自己说明了鉴权形态：

```
Dev mode (auto-detected): authentication disabled. This is allowed because the
server is bound to localhost (127.0.0.1). Do NOT expose this server to the network.
```

链路逐段验过（原始响应留档在 `.kb/runtime/memory/`）：

| 步骤 | 结果 |
| --- | --- |
| `ov-check` | rc=0，`{"configured": true, "server": "http://127.0.0.1:1933"}` |
| `memory begin` | 服务端真建会话：`session_id = d979d2d4-9fe1-498f-8e75-ab332da346f9`（account/user/agent 均为 default） |
| `memory add` ×2 | 服务端回读 `message_count` 依次为 1、2 |
| `memory status` | `server_message_count = 2`，`memories_extracted` 全 0（未提交前符合预期） |
| `memory commit` | `status=accepted`、`archive_uri=viking://session/<id>/history/archive_001`、`archived=true`；后台任务 `session_commit` → `completed`；留证落 `commit-2026-10-10T182740Z.json` |
| 磁盘核对 | `session/<id>/history/archive_001|002/{messages.jsonl,.abstract.md,.overview.md,.meta.json,.done}` 都在；`agent/default/memories/{identity.md,soul.md}` 已初始化 |

**结论：归档这条链路完全通了**——会话、消息、归档、任务、留证、回读全部有服务端与磁盘双证。

### 但记忆抽取失败了，原因不在插件

第二轮（4 条更有内容的对话）提交后，服务端日志给出根因：

```
WM creation failed: Error code: 402 - insufficient_balance_error (1008)
Failed to extract memories with v2: Error code: 402 - insufficient balance
Extracted 0 memories
MiniMax embedding failed: insufficient balance   ← embedding 连续失败触发熔断（50 连败）
```

也就是说：**抽取走的是 `ov.conf` 里配的 MiniMax（embm-01 向量 + MiniMax-Text-01 抽取），
而该账户余额不足（HTTP 402）**。归档不花模型所以成功；抽取与 embedding 全部失败，
所以两次提交的 `memories_extracted` 都是空的、`llm_token_usage` 为 0。

**要给用户的一句话**：把 MiniMax 账户充上值（或换一个可用的 embedding/vlm 端点），
同一条命令再跑一次就会真的抽出记忆。这是账户侧的事，不是插件侧的事。

### 真跑揪出的一个诚实性缺口（已修）

服务端在这种情况下仍把任务标成 `status="completed"`。按最早那版实现，插件会据此报
`extraction_ok: true`——**把"抽取失败"报成"抽取成功"**。现在 `memory commit` 输出改成：

```json
{"task_ok": true, "memories_total": 0, "llm_tokens": 0,
 "extraction_note": "任务完成但没有产出记忆、且 LLM 用量为 0：可能是本次会话确实没有可抽取的内容，也可能是模型调用失败（例如配额/余额不足）。请查服务端日志确认，不要默认当成抽取成功。"}
```

判据只看两件事：**抽出的条目数**与**LLM 用量**。零产出零用量时给提醒，不再默认成功。

### 线上完整链路（方案 B，2026-10-11）

把插件指向**线上生产实例**（豆包两模型）跑了一遍完整链路，结论是**真的产出了记忆，而且能召回**：

```
memory begin  -> session_id=20261011-114514-56428c2dd1264831
                 URI viking://user/<user>/sessions/<id>
memory add ×6 -> 服务端回读 message_count 1→6
memory commit -> status=accepted，archive_uri=…/history/archive_001，archived=true
                 后台 session_commit 任务 completed
                 memories_extracted={"memory_write": 3}
                 用量：llm 12,637+1,030=13,667 tokens；embedding 764 tokens；合计 14,431
memory status -> commit_count=1，message_count=0（已归档）
```

线上增量（对基线）：`sessions 0→1`、`total_memories 0→3`、`by_category {preferences:1, entities:2}`；
模型侧 `doubao-seed-2-0-lite-260428` +3 次调用 / +13,667 tokens、
`doubao-embedding-vision-251215` +6 次调用 / +784 tokens。

**召回验证**（`POST /api/v1/search/find`，query="SQL 缩进偏好"）：

| 命中 | score | 摘要 |
| --- | --- | --- |
| `viking://user/<user>/memories/preferences/当前用户/代码风格.md` | 0.544 | `- SQL一律使用4空格缩进` |
| `.../memories/entities/AI项目/openviking_online.md` | 0.249 | 线上 OpenViking：`doubao-embedding-vision-251215`(1024) + `doubao-seed-2-0-lite-260428`，volcengine，0.4.11 |
| `.../memories/entities/AI项目/openviking_local.md` | 0.235 | 本机那台 0.3.24 / MiniMax / 余额不足，不要和线上混淆 |

三条记忆与写入的事实一一对应——**计数、内容、召回三样都对上了**。
本次只在 `.tmp` 下的临时项目操作，正式项目一行未改。

## 七、自动捕获与召回（2026-10-17）

上面 §六 的链路是**手工驱动**的：`memory add` 写、`memory commit` 提交，跑一次就停。
OpenViking 官方 Codex 插件（`examples/codex-memory-plugin`）把同一套 API 接成了生命周期
自动链路，本插件按它的语义补齐了 hook：

| Codex 事件 | 本插件 hook | 行为 |
| --- | --- | --- |
| `SessionStart` | `sessionstart.py` | 建/复用会话；**空闲超过 30 分钟的会话补捕获并提交**（崩溃/未触发 SessionEnd 的兜底） |
| `UserPromptSubmit` | `userpromptsubmit.py` | 按本轮 prompt 检索 `viking://user` 下的记忆，注入 `additionalContext`（失败静默） |
| `Stop` | `stop.py` | **每轮**把 transcript 里新增的 user/assistant 轮次追加进会话（按水位去重） |
| `PreCompact` | `precompact.py` | 压缩前补捕获剩余轮次并提交会话 |
| `SessionEnd` | `sessionend.py` | 宽限期退出时提交（**Codex ≥ 0.145 才触发**；旧版本由 SessionStart 清扫兜底） |

会话 id 采用官方约定 `cx-<codex-session-id>`，与手工 `memory begin` 的 UUID 会话并存；
水位与 transcript 路径记在 `.kb/runtime/memory/host-sessions.json`。

### 怎么开

```jsonc
// .kb/config.json
"ov": {
  "memory_enabled": true,        // 总开关（默认 false）
  "remote_enabled": true,
  "url": "http://<openviking-host>:1933",   // 留空时回退读 ~/.openviking/ovcli.conf
  "api_key_file": "C:/Users/<you>/.openviking/api.key",
  "auto_capture": true,          // Stop 逐轮捕获
  "auto_recall": true,           // UserPromptSubmit 召回
  "capture_mode": "all",         // all | keyword（只在"记住/保存/记录"时捕获）
  "commit_token_threshold": 20000,
  "recall_limit": 6,
  "session_idle_ttl_minutes": 30
}
```

配置也可以只写 `~/.openviking/ovcli.conf`（官方 CLI 那份）：`ov.url` 为空时插件读它的
`url/api_key/account/user` 作回退，和官方插件一致。

### 边界

- **提交才会产生记忆**：Stop 只追加消息；阈值、PreCompact、SessionEnd、空闲清扫才 commit。
  commit 会消耗模型配额，所以默认阈值 2 万 token，不在每一轮提交。
- **hook 全部 fail-open**：服务不可达、鉴权失败、transcript 读不到，都只提示/静默，不影响对话。
- **本轮不做**：Node stdio MCP 代理、profile/技能目录注入、usage 报表（官方插件有，另行立项）。
- 本机 Codex 0.135 不支持 `SessionEnd`；`Stop + PreCompact + SessionStart 清扫` 已经覆盖
  正常退出、压缩和异常退出三种情况。

### 线上验证（2026-10-17）

对 `http://<openviking-host>:1933`（0.4.11）用真实 hook 跑过一轮：`Stop` 追加 2 条消息
（`pending_tokens=82`）→ `PreCompact` 提交 → 24 秒后抽取 **1 条记忆**（10,661 tokens），
落在 `viking://user/<user>/memories/preferences/当前用户/代码风格.md`；用
`memory recall --query "SQL 缩进偏好"` 第一条就命中它。会话留证
`cx-online-hook-10172110`，明细见 `docs/session-memory-hooks-ledger.md` 第五节。
