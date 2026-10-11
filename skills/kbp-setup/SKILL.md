---
name: kbp-setup
description: 初始化知识库项目：建立 .kb 运行时、同步引擎、注入知识库研发规范（Codex 入口，等价于 /kb-setup）
---

# kbp-setup（Codex 版 `/kb-setup`）

> 本文件由 `tools/build_codex_surface.py` 从 `commands/setup.md` 生成，请勿手改；
> 改流程请改命令源文件后重跑生成器。命令里的 `py -3` 是 Windows 写法，
> macOS/Linux 换成 `python3`。

# kbp-setup — knowledge-base-plugin 初始化

1. 确认当前目录是“知识库成品件仓库”的项目根（不是数据研发项目，也不是插件仓库）。
2. 定位插件根目录（含 `engine/` 与 `.claude-plugin/plugin.json`）：先试
   `echo $env:CLAUDE_PLUGIN_ROOT`（PowerShell）或 `${CLAUDE_PLUGIN_ROOT}`（sh）；
   找不到就在这些位置找：
   `~/.claude/plugins/cache/**/knowledge-base-plugin`、
   `~/.claude/plugins/marketplaces/*/plugins/knowledge-base-plugin`、
   `~/.codex/plugins/cache/**/knowledge-base-plugin`、
   `~/plugins/knowledge-base-plugin`（Codex 个人 marketplace 默认位置）。
3. 把 `<插件根>/engine` 复制到 `.kb/engine`（用 `py -3` 写 Python 复制，忽略 `__pycache__`）。
4. 初始化：`py -3 .kb/engine/kbp.py setup --mode mock --domain user`
   （live 模式接真实 metadata MCP / git remote；domain 默认 user，可换任意业务域）。
   **返回值里带 `vcs`，必须看**：`{"ok": false, "reason": …}` 说明版本控制层没起来
   （通常是本机没有 git）。这不影响 mock 体验，但知识库不会被版本化，
   **发布会被 git_commit 门拦下**——把 reason 原样告诉用户，别只说"初始化完成"。
5. 注入规范（按宿主选文件名）：
   - **Codex**（环境变量 `PLUGIN_DATA` 存在即为 Codex）：把
     `<插件根>/engine/templates/AGENTS.kb.md` 写入项目根 `AGENTS.md`（已存在则去重追加）；
     Codex 不读 `.claude/settings.json`，跳过权限白名单。
   - **Claude Code**：把 `<插件根>/engine/templates/CLAUDE.kb.md` 追加/写入项目 `CLAUDE.md`（去重），
     并把 `templates/settings.json` 的权限白名单合并进 `.claude/settings.json`。
6. 自检：`py -3 .kb/engine/kbp.py status`，告诉用户：
   - 知识流水线命令：kbp-generate → kbp-audit → kbp-review → kbp-publish → kbp-refresh → kbp-propose；
   - mock 模式开箱可体验；真实数据源需配置 live CLI；
   - 真实 OpenViking 发布：把 `config.json` 的 `mode` 改为 `live`、
     `ov.remote_enabled=true`、`ov.url` 指向 server，并设置 `OV_API_KEY`
     环境变量（或 `ov.api_key_file`），再跑 `py -3 .kb/engine/kbp.py ov-check`
     自检后发布。
