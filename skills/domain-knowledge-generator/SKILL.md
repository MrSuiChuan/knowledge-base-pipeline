---
name: domain-knowledge-generator
description: 数仓域知识生成方法论：MCP 6类元数据采集 + 5 步业务骨架 + 生成即审计 + 9 章节表级文档
---

# domain-knowledge-generator

被 /kb-generate 加载。产出物是“能支撑 Agent 推理”的导航 + 表级文档，不是文档堆。

## 采集纪律（无臆造）

每张表必须拿到 6 类知识：BASIC_INFO（表是谁的/多大/多频）、COLUMN_BASIC_INFO（字段语义）、
DDL_SQL、SCHEDULE_TASK、QUALITY_RULE、PARTITION_INFO。快照 `metadata-snapshot.json`
是调用留证与时间锚点；人只提供业务背景和口径选择。

## 5 步交互

1. 业务全景（主线如“注册→活跃→留存”、核心实体、scope）；
2. 实体/过程；
3. 场景 + 锚点表（每个场景锚定权威表，场景内全表扫描，严禁因表名跳表）；
4. 规则（口径/命名/状态机，concept+definition）；
5. 数据层与目标（goal→metrics→tables + 逐表业务语境）。

## 产物门

- `navigation.md`：全景/实体/场景锚点/规则/目标导航 + 推理纪律；
- 每表 9 章节文档：1 基础身份（自动）2 业务语境 3 字段语义（自动）4 上游口径 5 SQL 约束
  6 JOIN 关系 7 FAQ 8 质量 SLA 9 检索关键词；
- 生成完立即 /kb-audit；strict+publish 不过不发布。

占位就是占位：别把“（待补）”写成像结论的东西。
