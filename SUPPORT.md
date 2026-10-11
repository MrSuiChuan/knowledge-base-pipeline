# 获取支持

## 先看这里

| 你想做的事 | 读这个 |
| --- | --- |
| 先跑起来看看 | [README.md](README.md) 的「快速开始」；装完直接 `py -3 engine/kbp.py demo --domain user` |
| 弄清某个概念 | [docs/glossary.md](docs/glossary.md) |
| 不知道读哪份文档 | [docs/README.md](docs/README.md)（文档地图） |
| 接真实平台 / 真实 OpenViking | [docs/REPRODUCTION-NOTES.md](docs/REPRODUCTION-NOTES.md) |
| 接主流实时组件当知识源 | [docs/realtime-sources.md](docs/realtime-sources.md) |
| 门控为什么拦我 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 的审计与门控一节 |
| 想贡献 | [CONTRIBUTING.md](CONTRIBUTING.md)、[GOVERNANCE.md](GOVERNANCE.md) |
| 报安全问题 | [SECURITY.md](SECURITY.md)（**不要**开公开 issue） |

## 提问要带的东西

用 issue 模板提问时，请带上这四样——缺了维护者只能反过来问你一轮：

1. 你在做什么（命令原文）；
2. 期望什么、实际发生什么（**完整输出**，不要只贴一行）；
3. 环境（操作系统、Python 版本、插件版本、`mode`）；
4. 最小复现（能砍到多小就多小）。

## 支持范围

**支持**：安装与升级、mock 模式全流程、门控行为解释、采集层与本地实验环境、
文档与模板问题、缺陷修复。

**不支持**（不是"不礼貌"，是确实做不到）：

- 替使用者接通其内部平台的执行器与账号；
- 在维护者机器上复现只有你有权访问的环境；
- 为使用者的生产数据正确性背书——本插件给的是工艺与门控，不是数据担保。

## 响应预期

维护者尽力而为，不开 7×24 承诺。可参考的节奏：issue 初次回应 **7 个自然日内**；
安全报告按 [SECURITY.md](SECURITY.md) 的时点。超过两周没有任何动静，欢迎直接 ping 维护者。
