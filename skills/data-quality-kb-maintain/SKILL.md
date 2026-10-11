---
name: data-quality-kb-maintain
description: 质量规则维护方法论：实战长期事实 -> 提案（五资格）-> 引擎门禁 -> APPLIED -> Owner approve -> active
---

# data-quality-kb-maintain（沉淀）

被 /kb-propose 与 /kb-review 加载。下游测试流程在实战中发现的“这条以后都要测”才值得沉淀。

## 铁律

不直接手改 `rules/`，必走提案。沉淀是给知识库开的一个常开入口。

## 提案五资格

跨需求成立 / 长期成立 / 可量化 / 确定性匹配 / 有证据（全 true 才进）。

## 引擎门禁（五道）

1. schema：id/concept/pattern 齐全；
2. 重复：同 pattern / 同 id 已存在；
3. 冲突：同概念不同 pattern；
4. 单测：positive≥1 且 negative≥1（ambiguous 可选）；
5. 血缘：lineage 的 table.column 必须存在于元数据快照——禁裸字段名横切，防误命中别业务线同名列。

## 状态机

门禁过 → 写库 `status: APPLIED` + `final_status: READY_FOR_REVIEW` → Owner approve →
`status: active` + `final_status: APPROVED`。APPLIED≠REVIEWED 是治理窗口，/kb-review 收口。
