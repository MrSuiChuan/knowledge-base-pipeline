---
description: data-quality-kb-maintain：实战长期事实 -> 规则提案（五资格 + 引擎门禁），禁止手改 rules/
argument-hint: <长期事实描述>
allowed-tools: [Bash, Read, Write, AskUserQuestion]
---

# /kb-propose — 沉淀新规则

只在实战（数据测试/SDS 找表）发现“跨需求长期成立、可量化、有确定性匹配证据”的事实时才走本流程。

## 步骤

1. 与用户确认五资格：跨需求成立 / 长期成立 / 可量化 / 确定性匹配 / 有证据；
2. 组装提案 JSON：`candidate_rule`（id/concept/pattern/lineage/tests）+ `qualification`；
   血缘必须 `table.column` 且能在元数据快照中找到——**禁裸字段名横切**；
   tests 至少 positive 1 条 + negative 1 条（ambiguous 可选）；
3. 过引擎门禁：`py -3 .kb/engine/kbp.py propose --json-file <proposal>.json`
   （schema / 重复 / 冲突 / 单测 / 血缘五道检查）；
4. 门禁通过 → 规则写库 `status=APPLIED` + `final_status=READY_FOR_REVIEW`；
5. 提醒 Owner 走 `/kb-review` 终签（在此之前规则处于 APPLIED≠REVIEWED 中间态）。

铁律：**禁止直接 Write/Edit `.kb/repo/rules/`**——hook 会拦，沉淀必须走提案。
