---
name: kbp-refresh
description: disclosure-domain-skill：元数据漂移比对 -> 回灌基础身份/字段语义 -> drift report（Codex 入口，等价于 /kb-refresh）
---

# kbp-refresh（Codex 版 `/kb-refresh`）

> 本文件由 `tools/build_codex_surface.py` 从 `commands/refresh.md` 生成，请勿手改；
> 改流程请改命令源文件后重跑生成器。命令里的 `py -3` 是 Windows 写法，
> macOS/Linux 换成 `python3`。

# kbp-refresh — 反哺保鲜

平台元数据变了（owner/字段/调度），知识文档不能腐烂：

```
py -3 .kb/engine/kbp.py refresh --domain <domain>
```

引擎会：重新采集 → 与上一个 `metadata-snapshot.json` 比对（drift）→ 只回灌
“基础身份/字段语义”两节 → 写 `refresh-drift-*.json` 报告。

之后：

1. 业务语境 / SQL 约束 / FAQ 等人工章节若有口径调整，向用户提问（Codex 里直接在对话中问，等用户回复，不要自答） 确认后手改（不影响自动节）；
2. 重跑 `kbp-audit`（publish/strict）；
3. 重跑 `kbp-publish`（v2+）。

向用户说明局限：只反映在元数据里的变化能被反哺抓住；纯业务口径漂移要靠人。
