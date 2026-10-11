---
name: disclosure-domain-skill
description: 反哺方法论：重新拉 BASIC_INFO/COLUMN_BASIC_INFO，回灌基础身份与字段语义，识别元数据漂移
---

# disclosure-domain-skill（反哺）

被 /kb-refresh 加载。目的：元数据变了，知识别腐烂。

## 做法

- 重新采集元数据，与上一个 `metadata-snapshot.json` 比对，输出 drift（表/字段/old→new）；
- 只回灌“基础身份”“字段语义”两节（元数据能确定的）；
- 字段重新按业务概念分组、重新推断表类型/时间粒度/是否可重跑（记录进 drift 报告）；
- 业务语境 / SQL 约束 / FAQ 仍靠人，反哺不动。

## 闭环

回灌完成 = 内容变更：必须重跑 audit → publish（v2+）。
局限要讲清：只反映在元数据里的漂移才抓得到；纯业务口径漂移靠人补。
