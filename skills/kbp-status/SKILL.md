---
name: kbp-status
description: 查看知识库流水线状态：last_audit / last_publish / 规则终签态 / 待审提案（Codex 入口，等价于 /kb-status）
---

# kbp-status（Codex 版 `/kb-status`）

> 本文件由 `tools/build_codex_surface.py` 从 `commands/status.md` 生成，请勿手改；
> 改流程请改命令源文件后重跑生成器。命令里的 `py -3` 是 Windows 写法，
> macOS/Linux 换成 `python3`。

# kbp-status

```
py -3 .kb/engine/kbp.py status
py -3 .kb/engine/kbp.py snapshot show
```

汇报：domain、mode、last_generation、last_audit（id/passed/mode/level）、last_publish、
发布版本数、规则清单（APPLIED/active/READY_FOR_REVIEW）、待审提案数。若有
READY_FOR_REVIEW 项，提醒走 `kbp-review`。
