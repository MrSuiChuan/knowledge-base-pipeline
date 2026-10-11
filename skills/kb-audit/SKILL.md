---
name: kb-audit
description: 质检方法论：口径冲突审计 + 六层链接完整性 + 索引重建；结果不入 git，发布前必须 strict+publish
---

# kb-audit

被 /kb-audit 加载。生成即审计，审计是流水线第一道机器门。

## 三检

- conflict_audit：同名概念不同定义 → FAIL（带 spot_check_results 抽查）；
- link_audit：v41 六层完整性——
  L1 仓库 README→域导航 / L2 导航锚点→表文档 / L3 目标导航→表文档 /
  L4 表文档上游口径→上游表 / L5 JOIN→表文档 / L6 质量 SLA→规则 yaml；
  标 `changed_set_new_broken_introduced` 追踪新引入断链；
- index_rebuild：扫完重建域索引（updated/skipped 计数）。

## 纪律

- 最严级别 + mode=publish 时，冲突/断链不过不放行；
- 检出问题进 `.kb-pending-review/` / `.kb-rejected/`；
- 审计结果不入 git（本地留证），多人协作需各自重跑。
