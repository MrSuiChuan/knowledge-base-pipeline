# knowledge-base-plugin 架构文档

## 1. 流水线总览

```scss
采集(snapshot.fetch, MCP 6类知识)
  ↓ metadata-snapshot-*.json（时间锚点）
结构化(skeleton 5步 + render)
  ↓ navigation.md + 9章节表级文档
质检(audit.run_audit: conflict/link v41六层/index rebuild)
  ↓ .kb-audit-*.json（gitignore）
审阅(proposals: APPLIED → Owner approve → active)
沉淀(data-quality-kb-maintain: propose → 五道门禁 → APPLIED)
发布(sync.publish: git commit/tag + OV 同步 + manifest)
反哺(snapshot.diff → render 回灌自动章节 → refresh-drift 报告)
  ↓ 回到 audit/publish（反哺闭环）
```

发布侧说明：审计文件记录知识树 `content_hash`，publish 门以哈希比对为准；
`ov.remote_enabled=false` 时只做本地镜像（`ov_sync=local-mirror`），`mode=live`
且未启用远端同步器时发布直接拒绝。`ov.remote_enabled=true` 时发布先走
`ov_remote.push_files`：逐级建父目录（`/api/v1/fs/mkdir`）→
`content/write`（create/replace + wait 处理）→ `content/read` 回读校验，
全部成功才继续 git commit/tag 与 manifest 留证；任一步失败返回
`gate=ov_remote_sync`，不写成功清单。

## 2. 运行时布局

```
.kb/
  config.json          mode / domain / uri_root / audit_level / owners / git_enabled
  _state.json          last_generation/last_audit/last_publish/last_refresh/seq
  _context.md          状态镜像
  mock/meta.json       模拟平台元数据（6 类知识的事实源）
  repo/                git 版本化的成品件仓库
    README.md          domains 索引（L1 锚）
    domains/<domain>/navigation.md + skeleton.json + index.md
    domains/<domain>/tables/<table_id>.md
    rules/<domain>/<rule_id>.yaml
    proposals/<proposal_id>.json
    .kb-manifest.json  （发布清单，随库提交）
    .kb-audit-*.json   （gitignored）
    .kb-pending-review/ .kb-rejected/
  ov/                  mock OpenViking（viking://resources/... 镜像 + index.json）
  runtime/snapshots/   metadata-snapshot-*.json
  runtime/refresh-drift-*.json
  runtime/.kb-sync-state.json
  runtime/memory/session.json       # 会话记忆：绑定的 session_id 与提交历史
  runtime/memory/commit-<ts>.json   # 会话记忆：提交留证（task_id + 抽取任务终态）
  runtime/hook-logs/*.kb-hook-log.jsonl
```

## 3. 采集契约（snapshot）

每张表 6 类：

| 类别 | 回答的问题 |
| --- | --- |
| BASIC_INFO | 表是谁的/多大/多频 |
| COLUMN_BASIC_INFO | 字段语义 |
| DDL_SQL | 建表语句/SQL 约束 |
| SCHEDULE_TASK | 什么时候产出能拿数 |
| QUALITY_RULE | 有什么质量约束 |
| PARTITION_INFO | 按什么分区检索 |

来源三选一，由 `source` 决定（显式参数 > `.kb/config.json` 的 `snapshot.source` > 按 `mode` 兜底）：

| 来源 | 取值 | 说明 |
| --- | --- | --- |
| 本地 mock | `mock` | 读 `.kb/mock/meta.json`，开箱可体验 |
| 平台元数据 MCP | `platform-mcp` | CLI `snapshot --domain <d>`，要求 JSON stdout |
| 实时组件直采 | `oss:<组件id>` | 组件必须在 `engine/sources/registry.json` 登记；采集器把组件元数据翻译成 6 类契约 |

快照里的 `source` 如实记录本次来源；未登记的来源以 `source_unregistered` 拦下且不落盘。
每一行还可能带两个附注字段：`NOT_APPLICABLE`（该组件没有这一类知识，附理由）与
`COLLECT_FAILED`（本该采到但没采到，附原始错误）——六类的值本身仍按契约类型留空，
不塞假数据。详见 [realtime-sources.md](realtime-sources.md)。

快照是“采集留证 + 反哺漂移比对的基线”。

## 4. 业务骨架（skeleton 5 步）

1 全景 / 2 实体过程 / 3 场景（含 anchor_table，须在快照中）/ 4 规则 / 5 数据层目标。
`validate_ready` 在 generate 前强制：全景非空、场景≥1、锚点/范围表都在快照里。

## 5. 质检（audit）

审计 payload 稳定字段契约：generator / audit_level / mode / conflict_audit
（findings + spot_check_results）/ link_audit（v41_six_layers + broken +
changed_set_new_broken_introduced）/ index_rebuild（updated/skipped）/ audit_scope。

- 冲突 = 同概念不同定义（文本确定性比对）；
- 六层：L1 README→navigation；L2 锚点→表文档；L3 目标→表文档；L4 上游→表文档；
  L5 JOIN→表文档；L6 SLA 规则引用→rules/*.yaml；
- strict+publish 时任何 FAIL 不放行；审计结果不入 git。

## 6. 提案与审阅（proposals）

引擎门禁五检：schema / 重复 / 冲突 / 单测（positive≥1+negative≥1）/ 血缘
（table.column 必须存在于最新快照，禁裸字段横切）。

状态机：

```
PENDING →(门禁过)→ 写库 APPLIED + READY_FOR_REVIEW
                  →(Owner approve)→ active + APPROVED
                  →(门禁败)→ REJECTED（proposal 留档）
```

`/kb-review` 列出待审；approve 校验 owner 登记且与规则 owner 一致（禁代签）。

## 7. 发布（sync）

kb_publish_guard 条件：最近审计存在、passed、mode=publish、level 匹配配置、且审计时间晚于
repo 内任何内容变更。随后：远端推送（若启用，先于本地落证）→ git
add/commit/tag(kb-vN) → 本地 OV 镜像（写入 .kb/ov + 索引）→
manifest/sync-state/hook-log 留证 →（可选）同步 data-development-plugin mock kb 索引。

消费方同步按项目**已经初始化**的运行时目录判定，不写死一家：
`.data-dev/mock/kb/index.json`（离线数开插件）或 `.rtd/mock/kb/index.json`（实时数开插件）。
两个都没有时返回 `consumer_sync.ok=false` 并列出候选路径——发布本身不因此回滚，但结果必须可见。

## 8. 反哺（refresh）

重新采集 → 与上一份快照 diff（BASIC_INFO/COLUMN_BASIC_INFO）→ 仅重写
“1 基础身份 / 3 字段语义”两节 → 写 refresh-drift-*.json。之后必须重跑 audit/publish。

## 9. Hook 门

| Hook | 条件 | 动作 |
| --- | --- | --- |
| kb_publish_guard | publish/同步命令且审计缺失/过期/未过 | block |
| audit_completion_guard | 同步类工具审计过期 | 软提醒（allow+notes） |
| rules_direct_write_guard | Write/Edit 目标在 .kb/repo/rules/ | block |
| setup_guard | 无 .kb 时调用知识库 CLI | block |

## 10. 测试

```bash
python -m unittest discover -s tests -v
```

覆盖：audit 通过/冲突 FAIL/断链 FAIL、publish 门（无审计/审计后/审计后内容变更）、
rules 直改拦截、提案五道门禁、approve 生命周期、demo 端到端（v1→漂移→v2）、hook 冒烟。
