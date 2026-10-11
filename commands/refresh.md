---
description: disclosure-domain-skill：元数据漂移比对 -> 回灌基础身份/字段语义 -> drift report
argument-hint: "[--domain <domain>]"
allowed-tools: [Bash, Read, Write, AskUserQuestion]
---

# /kb-refresh — 反哺保鲜

平台元数据变了（owner/字段/调度），知识文档不能腐烂：

```
py -3 .kb/engine/kbp.py refresh --domain <domain>
```

引擎会：重新采集 → 与上一个 `metadata-snapshot.json` 比对（drift）→ 只回灌
“基础身份/字段语义”两节 → 写 `refresh-drift-*.json` 报告。

之后：

1. 业务语境 / SQL 约束 / FAQ 等人工章节若有口径调整，AskUserQuestion 确认后手改（不影响自动节）；
2. 重跑 `/kb-audit`（publish/strict）；
3. 重跑 `/kb-publish`（v2+）。

向用户说明局限：只反映在元数据里的变化能被反哺抓住；纯业务口径漂移要靠人。
