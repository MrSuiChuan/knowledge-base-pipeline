---
name: Bug 报告
about: 某个环节的行为与文档不符、或直接报错
title: "[bug] "
labels: bug
---

## 发生了什么

<!-- 期望什么、实际发生什么。完整输出比一行摘要有用得多。 -->

## 最小复现

```bash
# 从哪一步开始、敲的什么命令
```

## 环境

- 操作系统：
- Python 版本（`py -3 -V`）：
- 插件版本（`.claude-plugin/plugin.json` 的 `version`）：
- `mode`（mock / live）：
- 宿主（Claude Code / Codex / 其他）：

## 如果是门控拦住了你

贴出引擎返回的 **gate 键**（例如 `kb_publish_guard` / `setup_guard` / `source_unregistered`）
和完整输出，并说明你**认为**它该不该拦——判断错了也是有效报告。

## 其他

<!-- 有没有 `.kb/` 下的产物可以脱敏后贴出来？注意：不要把密钥、内网地址、真实数据贴进公开 issue。 -->
