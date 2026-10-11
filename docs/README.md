# 文档地图

按"你手上是什么问题"找，不按文件名字母序找。

## 第一次接触

| 我想…… | 读 |
| --- | --- |
| 三分钟跑起来看看 | [../README.md](../README.md) 的「快速开始」；装完 `py -3 engine/kbp.py demo --domain user` |
| 知道它到底解决什么问题 | [../README.md](../README.md) 开头的「七个环节」表 |
| 弄清术语 | [glossary.md](glossary.md) |
| 明白门控为什么拦我 | [ARCHITECTURE.md](ARCHITECTURE.md) 的审计 / 门控 / hook 三节 |
| 知道哪些事它做不到 | [../SECURITY.md](../SECURITY.md) 的 Known limits，以及 [glossary.md](glossary.md) 末尾的"常见误解" |

## 按环节读

| 环节 | 文档 |
| --- | --- |
| 采集（平台 MCP / 实时组件 / mock） | [ARCHITECTURE.md](ARCHITECTURE.md) 第 3 节；实时组件见 [realtime-sources.md](realtime-sources.md) |
| 结构化（骨架 5 步 + 生成） | [ARCHITECTURE.md](ARCHITECTURE.md) 第 4 节 |
| 质检（口径冲突 / 六层链接 / 索引） | [ARCHITECTURE.md](ARCHITECTURE.md) 第 5 节 |
| 审阅与沉淀（提案、终签） | [ARCHITECTURE.md](ARCHITECTURE.md) 第 6 节 |
| 发布（git + OpenViking 双轨） | [../README.md](../README.md) 的发布一节 + [ARCHITECTURE.md](ARCHITECTURE.md) 第 1 节 |
| 反哺（漂移与回灌） | [realtime-sources.md](realtime-sources.md) 第八节（组件侧漂移）；平台侧见 ARCHITECTURE 第 1 节 |
| 会话记忆（为什么没记录、怎么开） | [session-memory.md](session-memory.md) |
| 本地实验环境（起真实组件） | [realtime-sources.md](realtime-sources.md) 第五、八节 |

## 想参与 / 想发版

| 我想…… | 读 |
| --- | --- |
| 提第一个 PR | [../CONTRIBUTING.md](../CONTRIBUTING.md) |
| 知道谁能合并、谁能发版 | [../GOVERNANCE.md](../GOVERNANCE.md) |
| 发一个版本 | [release-process.md](release-process.md) |
| 知道仓库包含哪些第三方东西 | [third-party-dependencies.md](third-party-dependencies.md)、[../NOTICE](../NOTICE) |
| 看这次开源验收的结论 | [apache-readiness-audit.md](apache-readiness-audit.md) |
| 提安全报告 | [../SECURITY.md](../SECURITY.md)（**不要**开公开 issue） |

## 三份"过程记录"（不是教程，是证据）

- [REPRODUCTION-NOTES.md](REPRODUCTION-NOTES.md)：怎么从零复现出这套插件、连接器契约长什么样；
- [realtime-sources.md](realtime-sources.md)：实时组件采集层的三条纪律、真跑记录、以及**真跑才暴露的缺陷**；
- [apache-readiness-audit.md](apache-readiness-audit.md)：按 Apache 标准四维度做的开源就绪审计，逐条给结论。

> 这些文件里凡写"未验证"的地方，就是**真的没有证据**，不是客气话。
