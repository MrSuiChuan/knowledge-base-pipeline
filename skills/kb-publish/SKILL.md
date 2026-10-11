---
name: kb-publish
description: 发布方法论：git 入库 + OpenViking 同步双轨；kb_publish_guard/audit_completion_guard 门控
---

# kb-publish

被 /kb-publish 加载。发布 = git（版本化/可回滚）+ OpenViking 同步（对 Agent 可见），缺一不可。

## 门控

- kb_publish_guard（PreToolUse 硬拦）：最近审计必须存在、passed、mode=publish、
  level=strict、且晚于最近内容变更；
- audit_completion_guard：同步类工具在审计缺失/过期时至少软提醒；
- 留证：`.kb-manifest.json`（随库提交）、`.kb-sync-state.json`、`*.kb-hook-log.jsonl`。

## 双轨

只入 git 不同步 OV → Agent 拿不到；只同步 OV 不入 git → 丢版本历史。
发布后把 URI 清单给用户；可选把新表文档同步进 data-development-plugin 的 mock kb 索引。
