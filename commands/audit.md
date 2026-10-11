---
description: 质检：口径冲突 + 六层断链 + 索引重建；publish/strict 不过不放行
argument-hint: "[--domain <domain>] [--mode publish|local] [--level strict|standard]"
allowed-tools: [Bash, Read]
---

# /kb-audit — 生成即审计

```
py -3 .kb/engine/kbp.py audit --domain <domain> --mode publish --level strict
```

审计内容（结果写 `.kb/repo/.kb-audit-*.json`，gitignore 不入库）：

- conflict_audit：同名概念不同定义 → FAIL，附带 spot_check_results 抽查；
- link_audit：六层链接完整性（v41_six_layers），并标 `changed_set_new_broken_introduced`；
- index_rebuild：扫完重建域索引。

FAIL 时把 issue 清单给用户看并修复；strict+publish 通过前 `/kb-publish` 会被
kb_publish_guard 拦死。提醒：审计结果不入 git，多人协作各自重跑。
