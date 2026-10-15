---
description: 发布：git 入库 + OpenViking 同步双轨（kb_publish_guard 强制审计新鲜度）
argument-hint: "[--domain <domain>] --reason <说明> [--consumer-root <data-dev 项目根>]"
allowed-tools: [Bash, Read, AskUserQuestion]
---

# /kb-publish — 发布知识

先自查：`py -3 .kb/engine/kbp.py status`；若 last_audit 不是 strict+publish 或内容晚于审计，
`/kb-publish` 会被 guard 拦死——先跑 `/kb-audit`。

```
py -3 .kb/engine/kbp.py publish --domain <domain> --reason "<发布说明>"
```

发布做三件事：

1. git 入库 + 打版本 tag（kb-vN，本地 git 仓库在 `.kb/repo/`）；
2. OpenViking 同步：本地镜像写入 `.kb/ov/` 并建立 `viking://resources/...` 索引；
   若 `ov.remote_enabled=true`，还会先真实推送到配置的 OpenViking server
   （逐级建目录 → content/write → 回读校验），全部成功才落本地清单；
3. 留证：`.kb-manifest.json`（随库提交，记录 `ov_sync=remote|local-mirror` 与远端
   推送/校验计数）、`.kb-sync-state.json`、hook 日志。

可选：`--consumer-root <开发插件项目根>` 会把新表文档同步进该项目的知识索引，
让它的设计/定位阶段直接能找到这张表。两个开发插件各写各的运行时目录，生产端按
**已经存在的那个**判定：`.data-dev/mock/kb/index.json`（离线数开）或
`.rtd/mock/kb/index.json`（实时数开）。

**这一步有前置条件**：那个 `index.json` 必须**已经存在**（数开项目跑过 `/setup` 并用过一次
知识客户端才会建）。没建的话同步一行都不会做——所以返回值里带了 `consumer_sync`：

```jsonc
"consumer_sync": {"ok": true, "index": "<实际写入的索引路径>", "added": ["viking://resources/…"]}
"consumer_sync": {"ok": false, "reason": "consumer 两个开发插件的 kb 索引都不存在: …"}
```

**看到 `ok: false` 就要告诉用户**"先去那个数开项目跑 `/setup`，再重新 `/kb-publish` 一次"，
不要只报"发布成功"。发布本身（git + OV）确实成功了，所以这里不判失败、不回滚——
但静默丢弃是错的（这条链原来就是这么丢的）。

发布完把 URI 清单、版本号、以及 `consumer_sync` 的结果一起汇报给用户。

## live 远端发布准备

在 `.kb/config.json` 设置：

```jsonc
{
  "mode": "live",
  "ov": {
    "remote_enabled": true,
    "url": "http://<server>:1933",
    "api_key_env": "OV_API_KEY",  // 或 ov.api_key_file 指向本地密钥文件
    "scope_readme": false         // 共享 scope 建议 false，避免覆盖根 README
  }
}
```

密钥只从环境变量 `OV_API_KEY`（或本地密钥文件）读取，绝不写入 config.json/
manifest。发布前可跑 `py -3 .kb/engine/kbp.py ov-check` 做只读连通性自检。
