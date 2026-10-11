---
description: 查看知识库流水线状态：last_audit / last_publish / 规则终签态 / 待审提案
argument-hint: "[--domain <domain>]"
allowed-tools: [Bash, Read]
---

# /kb-status

```
py -3 .kb/engine/kbp.py status
py -3 .kb/engine/kbp.py snapshot show
```

汇报：domain、mode、last_generation、last_audit（id/passed/mode/level）、last_publish、
发布版本数、规则清单（APPLIED/active/READY_FOR_REVIEW）、待审提案数。若有
READY_FOR_REVIEW 项，提醒走 `/kb-review`。
