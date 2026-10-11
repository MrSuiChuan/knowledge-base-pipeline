---
name: 配置 / 接入求助
about: 接真实平台、真实 OpenViking 或实时组件时卡住了
title: "[config] "
labels: configuration
---

## 你要接的是什么

- [ ] 平台元数据 MCP（`config.cli.metadata`）
- [ ] 真实 OpenViking 发布（`ov.remote_enabled` / `ov.url` / API Key）
- [ ] git 远端发布
- [ ] 实时组件采集（`sources.<组件id>`，见 docs/realtime-sources.md）
- [ ] 其他：

## 卡在哪一步

```bash
# 命令 + 完整输出（密钥请打码，不要贴真值）
```

## 自检结果

```bash
py -3 engine/kbp.py status
py -3 engine/kbp.py ov-check          # 只有接 OpenViking 时才有意义
py -3 engine/kbp.py sources list      # 只有接实时组件时才有意义
```

## 配置形状（脱敏后）

<!-- 贴 .kb/config.json 的结构即可，密钥写 <redacted>。 -->

## 你查过哪些文档

<!-- 例如 docs/README.md 的哪一节、docs/REPRODUCTION-NOTES.md。查过但没解决，说明文档该补。 -->
