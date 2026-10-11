# 第三方依赖与边界

开源仓库最容易被问的两个问题：**仓库里有没有别人的代码/二进制？**、**文档里的那些产品名
是不是表示关联？** 这份文件回答这两个，并把边界划到"谁在谁的机器上跑什么"。

## 一、仓库内包含什么

| 类别 | 情况 |
| --- | --- |
| 第三方源码 / 二进制 | **没有**。本仓库全部内容为项目作者自著（`engine/` `hooks/` `tools/` `commands/` `skills/` `docs/` `tests/`） |
| 运行时依赖 | **只用 Python 标准库**（`json` `re` `socket` `subprocess` `urllib` `hashlib` `pathlib` `datetime` 等），没有 pip 依赖、没有虚拟环境要求 |
| 随仓库分发的数据 | 只有示例与占位数据（`.kb/mock/meta.json` 的 mock 元数据、模板文件）；不含任何真实业务数据 |
| 字体 / 图标 / 图片 | 没有 |

依赖清单可以机器核对：`python tools/validate_oss.py` 之外的 CI 扫描会拒绝常见密钥样式；
运行时是否引入第三方库，由"只用标准库"这条纪律约束（新增 import 会在评审时被问）。

## 二、测试时会在**使用者的机器上**跑什么

这一步不改变上面的结论：这些组件**不在本仓库内分发**，是使用者自己按文档下载并运行的。

| 场景 | 使用者自备的东西 | 本仓库提供什么 |
| --- | --- | --- |
| 接平台元数据 MCP（live 模式） | 使用者自己的 metadata CLI | 只调用 `config.cli.metadata`，不打包、不内置 |
| 接真实 OpenViking 发布 | 使用者的 OpenViking 服务与 API Key | 只发 HTTP（`engine/core/ov_remote.py`），凭证来自环境变量或本地密钥文件 |
| 接主流实时组件当知识源 | 使用者自己装的 Kafka / StarRocks / Doris / ClickHouse / Pulsar / Flink | 采集器 + 组件注册表 + 本地起停配方（[realtime-sources.md](realtime-sources.md)），**不下载、不安放二进制** |
| 跑单测 | 只需要 Python | 全部用例都用桩，不依赖任何外部组件；唯一真实 socket 是探活用例里临时开的本机端口 |

已实测过的组件版本与来源（含下载地址、镜像源、踩过的坑）都记在
[realtime-sources.md](realtime-sources.md) 与 `engine/sources/registry.json` 的 `verified` 字段里，
作为**可复现实验记录**存在，不构成对这些组件的再分发。

## 三、许可与声明

- 本项目自身：**Apache-2.0**（见 [LICENSE](../LICENSE) 与 [NOTICE](../NOTICE)）；
- 使用者自行获取的第三方组件：各自的许可归各自所有者，本项目的许可**不覆盖**它们；
- 本仓库不包含需要额外声明（NOTICE）的第三方作品，因此 `NOTICE` 里只有本项目自身信息与边界说明。

## 四、名称与商标

文档中出现的第三方名称（Apache Kafka、Apache Flink、Apache Pulsar、Apache Doris、StarRocks、
ClickHouse、Debezium、OpenViking 等）**只用于说明兼容对象与实测事实**。
不表示这些项目或它们的所属组织对本项目的赞助、背书、认证或任何形式的关联。
相关名称与商标归各自所有者；本项目名称与标识归项目所有者。

## 五、发现遗漏怎么办

如果某处实际上包含或再分发了第三方内容而本文未记录：按 [../SUPPORT.md](../SUPPORT.md) 提 issue，
或按 [../SECURITY.md](../SECURITY.md) 报（若涉及密钥/隐私）。这类问题按缺陷处理，不按"文档补充"处理。
