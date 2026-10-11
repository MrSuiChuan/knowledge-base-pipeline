---
description: 记会话：把这一轮的要点批量写进当前会话（收工前再 commit 触发记忆抽取）
argument-hint: "[要点文本，或留空让 Agent 从本轮对话里提炼]"
allowed-tools: [Bash, Read, Write]
---

# /kb-remember — 记会话

把**这一轮真正发生的事**写进 OpenViking 的会话里。它不是"写知识"——写知识走 `/kb-publish`；
这里记的是会话本身，`commit` 之后由 OpenViking 抽取成长期记忆（user/agent 记忆目录）。

## 前置（缺一条就别往下走）

1. 项目已 `/kb-setup`，且 `.kb/config.json` 的 `ov.memory_enabled` 是 `true`；
2. `ov.url` 指向**你真正要记的那台** OpenViking（本仓库有文档说明怎么分辨两台实例）；
3. 自检一下：`py -3 .kb/engine/kbp.py ov-check` —— 要看到 `ready_ok: true`。
   `ready_ok: false` 说明模型端点不可用（余额/鉴权/provider），**先修好再记**，
   否则会白提交一次并产出 0 条记忆。

## 怎么做

1. **先建会话（没有绑定时）**：

```bash
py -3 .kb/engine/kbp.py memory begin
```

2. **把要点落成一个 JSON**（条数不限，超过 100 条会自动分批）：

```json
{"messages": [
  {"role": "user", "content": "<这一轮用户提出的要求/给出的约束>"},
  {"role": "assistant", "content": "<这一轮真正做了什么、结论是什么>"}
]}
```

写进临时文件后批量追加：

```bash
py -3 .kb/engine/kbp.py memory batch --json-file <临时文件路径>
```

3. **收工前提交**（可选 `--no-wait` 只触发不等待）：

```bash
py -3 .kb/engine/kbp.py memory commit
py -3 .kb/engine/kbp.py memory status      # 回读 message_count / memories_extracted
```

## 写什么、不写什么

**要写**：用户的偏好与约束、这次确认下来的口径、踩过的坑与结论、环境的真实事实
（哪台实例、什么版本、什么模型）。这些是"下次还用得上"的东西。

**不要写**：密钥与口令、内网地址、真实业务数据、没有发生过的推测。
写进去的是长期记忆，不是草稿纸——记错比不记更糟。

**判断标准**：这条内容如果三个月后自己看到，能不能少踩一次坑？能，就写。

## 汇报要求

做完把三样报给用户：抽出了几条记忆（`memories_total`）、`llm_tokens` 用量、
以及留证文件路径（`.kb/runtime/memory/commit-<ts>.json`）。
若 `extraction_note` 非空，**原样告诉用户**——那说明任务完成了但没产出记忆，别报成成功。
