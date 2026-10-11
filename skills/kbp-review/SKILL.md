---
name: kbp-review
description: Owner 终签：列出 APPLIED/READY_FOR_REVIEW 提案并 approve（收口治理窗口）（Codex 入口，等价于 /kb-review）
---

# kbp-review（Codex 版 `/kb-review`）

> 本文件由 `tools/build_codex_surface.py` 从 `commands/review.md` 生成，请勿手改；
> 改流程请改命令源文件后重跑生成器。命令里的 `py -3` 是 Windows 写法，
> macOS/Linux 换成 `python3`。

# kbp-review — 审阅（Owner 终签）

机器门禁 APPLIED ≠ 人审完。先列出待审：

```
py -3 .kb/engine/kbp.py review list
py -3 .kb/engine/kbp.py rule list
```

对每条 `final_status: READY_FOR_REVIEW` 的规则：

1. 向用户提问（Codex 里直接在对话中问，等用户回复，不要自答） 向该业务线 Owner 确认（规则 owner 与审批人必须一致）；
2. 终签：`py -3 .kb/engine/kbp.py rule approve --proposal-id <DQ-...> --owner <owner> --reason "..."`；
3. 确认 status 变成 `active`、final_status 变成 `APPROVED`。

向用户说明中间态风险：APPLIED 后规则已落库并可能被运行时消费，Owner 未签前不要长时间挂着。
