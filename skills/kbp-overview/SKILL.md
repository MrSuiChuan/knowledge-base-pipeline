---
name: kbp-overview
description: 查看知识库流水线全貌：采集→结构化→质检→审阅→发布→反哺→沉淀（Codex 入口，等价于 /kb-overview）
---

# kbp-overview（Codex 版 `/kb-overview`）

> 本文件由 `tools/build_codex_surface.py` 从 `commands/overview.md` 生成，请勿手改；
> 改流程请改命令源文件后重跑生成器。命令里的 `py -3` 是 Windows 写法，
> macOS/Linux 换成 `python3`。

# knowledge-base-plugin 总览

把“生成数仓知识库”跑成一条有门控的工艺流水线，七个环节各拧一个矛盾侧面：

| 环节 | 矛盾 | 怎么拧 |
| --- | --- | --- |
| 采集 | 隐性→显性 且不臆造 | MCP 6 类知识 + metadata-snapshot 时间锚点 |
| 结构化 | 散点→可推理骨架 | 5 步骨架 + 场景锚点表 + 推理纪律 |
| 质检 | 口径不冲突、不断链 | conflict/link/index 三检，publish/strict 不过不放行 |
| 审阅 | 质量有人负责 | Owner 终签（APPLIED≠REVIEWED 要收口） |
| 发布 | 版本化 + 可发现 | git + OpenViking 双轨 + guard 门控 |
| 反哺 | 保持新鲜 | 元数据回灌基础身份/字段语义 + drift 报告 |
| 沉淀 | 从衰减→生长 | 提案五道门禁 + approve，不手改 rules/ |

## 三个闭环

- 生成闭环：采集→结构化→质检→审阅→发布；
- 消费闭环：`viking://resources/` 被 data-development-plugin 的 SDS 找表与下游测试消费；
- 反哺闭环：元数据漂移反向拽新知识（kbp-refresh），实战沉淀正向养厚知识（kbp-propose）。

## 命令

kbp-setup kbp-generate kbp-audit kbp-review kbp-propose kbp-publish kbp-refresh kbp-status

引擎：`py -3 .kb/engine/kbp.py --help`；`demo` 可在 mock 目录一次跑通 v1→漂移→v2 全流程。
