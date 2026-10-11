---
name: kbp-generate
description: domain-knowledge-generator：5 步业务骨架 + 元数据快照 -> navigation.md + 9 章节表级文档（Codex 入口，等价于 /kb-generate）
---

# kbp-generate（Codex 版 `/kb-generate`）

> 本文件由 `tools/build_codex_surface.py` 从 `commands/generate.md` 生成，请勿手改；
> 改流程请改命令源文件后重跑生成器。命令里的 `py -3` 是 Windows 写法，
> macOS/Linux 换成 `python3`。

# kbp-generate <domain> — 生成域知识

把隐性知识外部化为可审计的结构化文件。先采集、后结构化、再校验章节完整。

## 第 0 步：确认快照

`py -3 .kb/engine/kbp.py snapshot fetch --domain <domain>`（无快照不许生成：采集铁律=不臆造）。
告诉用户快照里抓到几张表、6 类知识是否齐全。

## 第 1-5 步：业务骨架（每步一次 向用户提问（Codex 里直接在对话中问，等用户回复，不要自答） 收集，逐步落盘）

用 `skeleton step --step N --json-file <fragment>.json` 逐次写入，引擎校验每步必填：

1. 业务全景（主线/核心实体/scope）；
2. 实体与过程；
3. 场景（每个场景必须给锚点表，场景内全表扫描）；
4. 规则（口径/命名/状态机，concept+definition）；
5. 数据层与目标（goal→metrics→tables，逐表业务语境/SQL 约束/FAQ/关键词）。

## 第 6 步：校验并生成

```
py -3 .kb/engine/kbp.py skeleton validate --domain <domain>
py -3 .kb/engine/kbp.py generate --domain <domain>
```

生成器产出 `navigation.md`（导航/锚点表/推理纪律）与每表 9 章节文档
（基础身份、业务语境、字段语义、上游口径、SQL 约束、JOIN 关系、FAQ、质量 SLA、检索关键词）；
“基础身份/字段语义”由元数据自动回灌，其余章节若有占位必须如实汇报，不许假装写完了。

## 收尾

提醒用户下一步：`kbp-audit`（质检不过不许发布）。
