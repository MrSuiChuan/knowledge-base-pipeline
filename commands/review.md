---
description: Owner 终签：列出 APPLIED/READY_FOR_REVIEW 提案并 approve（收口治理窗口）
allowed-tools: [Bash, Read, AskUserQuestion]
---

# /kb-review — 审阅（Owner 终签）

机器门禁 APPLIED ≠ 人审完。先列出待审：

```
py -3 .kb/engine/kbp.py review list
py -3 .kb/engine/kbp.py rule list
```

对每条 `final_status: READY_FOR_REVIEW` 的规则：

1. AskUserQuestion 向该业务线 Owner 确认（规则 owner 与审批人必须一致）；
2. 终签：`py -3 .kb/engine/kbp.py rule approve --proposal-id <DQ-...> --owner <owner> --reason "..."`；
3. 确认 status 变成 `active`、final_status 变成 `APPROVED`。

向用户说明中间态风险：APPLIED 后规则已落库并可能被运行时消费，Owner 未签前不要长时间挂着。
