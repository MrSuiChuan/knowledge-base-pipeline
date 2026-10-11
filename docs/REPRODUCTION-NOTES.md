# knowledge-base-plugin 设计说明、契约与已知边界

本插件把"数据仓库知识生成与维护"做成一条**七环节门控流水线**，让知识库从"写
文档"变成"可审计、可版本化、可被 Agent 确定性消费的成品件仓库"：

```
采集 → 结构化 → 质检 → 审阅 → 发布 → 反哺 → 沉淀
```

## 1. 运行时与产物契约

项目初始化后出现 `.kb/`：

```text
.kb/
  config.json         mode / domain / uri_root / audit_level / owners
  _state.json         last_generation / last_audit / last_publish ...
  mock/               mock 平台元数据（6 类知识的事实源）
  repo/               git 版本化的成品件仓库
    domains/<domain>/ navigation.md + skeleton.json + tables/<table>.md
    rules/<domain>/   <rule_id>.yaml
    proposals/        <rule_id>.json
    .kb-manifest.json 发布清单
  ov/                 mock OpenViking 同步层（viking://resources/... 镜像）
  runtime/            snapshots / sync-state / hook-logs / reviews
```

发布 URI 根由 `config.uri_root` 决定（默认 `viking://resources/`）；消费方
（data-development-plugin）只读该前缀下的知识；本地镜像/消费索引全链路跟随
uri_root。

## 2. 关键机制

- 采集无臆造：mock 元数据源（`.kb/mock/meta.json`）与 live metadata MCP 二选一；
  无快照禁止 generate；
- 生成即审计：`/kb-generate` 后必须 audit（strict+publish）才能 publish；内容在
  审计后变更 → guard 拒绝；
- 沉淀必走提案：hooks 直接拦 `.kb/repo/rules/**` 的 Write/Edit；
- 反哺是部分回灌：只自动重写元数据可确定的章节，人工章节保留；
- 状态与留证：`_state.json` 机器写；`_context.md` 镜像；审计默认不入 git。
- 审计锚点：每次 audit 记录知识树 `content_hash`，publish 门比对当前哈希
  （touch/改状态都不能伪造"已审计"）。
- 机器资产保护：`.kb/_state.json`、`.kb/runtime/**`、审计/发布清单文件禁止工具
  写入；Bash 对 touch/mv/rm 这些路径同样拦截。

## 3. 已知边界（诚实记录）

1. **live OpenViking HTTP 同步器已内置，默认关闭**：`ov.remote_enabled=false`（默认）时发布只写
   本地镜像（manifest 记录 `ov_sync=local-mirror`）；`mode=live` 且未启用远端
   同步器时发布会被 `ov_live_not_configured` 拒绝，不会假装同步成功。metadata
   MCP CLI、git remote 推送仍需接入真实环境校准。

   **真实远端接入（v1.2.0 起内置 HTTP 同步器）**：

   ```jsonc
   // .kb/config.json
   {
     "mode": "live",
     "uri_root": "viking://resources/",
     "ov": {
       "remote_enabled": true,
       "url": "http://<server>:1933",
       "api_key_env": "OV_API_KEY",      // 密钥只从环境变量/密钥文件读
       "api_key_file": "",               // 或本地密钥文件（首行），不入 git
       "account": "",                    // 可选 X-OpenViking-Account
       "user": "",                       // 可选 X-OpenViking-User
       "timeout": 120,
       "wait": true,
       "scope_readme": false   // 共享 uri_root 时保持 false，避免覆盖根 README
     }
   }
   ```

   传输器直接调 OpenViking HTTP API：`fs/mkdir` 逐级建父目录 →
   `content/write`（create/replace，wait 等语义+向量处理）→
   `content/read` 回读逐字校验。任一步失败 publish 即被 `ov_remote_sync`
   阻断，manifest 不写成功条目。`py -3 engine/kbp.py ov-check` 可做只读自检。
2. **"长期事实"判定靠人/主 agent**：插件做五项结构校验，不替代下游对"跨需求
   长期成立"的业务判断。
3. **口径冲突审计用确定性文本规则**（概念=定义 精确比对），语义级冲突与
   "锚点还在但语义过时"仍需人工抽样。
4. **六层链接是确定性实现**：L1 README→导航 / L2 锚点→表 / L3 目标→表 /
   L4 上游→表 / L5 JOIN→表 / L6 SLA→规则；只保证"断链抓得住"。
5. **规则 YAML 子集解析器**：只支持本插件产出的扁平键+列表结构；外部手写复杂
   YAML 需第三方解析器。
6. **APPLIED≠REVIEWED 中间态窗口被保留**：机器门禁写库后、Owner 终签前存在
   治理窗口，由 `/kb-review` 与 SessionStart 提醒收口，不自动审批。
7. **hooks.json 默认 `py -3`（Windows）**：macOS/Linux 可运行
   `python3 tools/adapt_hooks.py` 自动切换为 `python3`。

## 4. 与 data-development-plugin 的关系

- 上游：本插件发布到 `viking://resources/`；
- 消费：data-development-plugin 的 SDS 阶段（kb_scope_guard 只允许
  `knowledge.uri_prefix`）；
- 联调：`/kb-publish --consumer-root <data-dev 项目根>` 会把新表文档同步进该
  项目的 `.data-dev/mock/kb/index.json`，mock 模式下 SDS 立即能搜到。

## 5. 建议演进

1. 接真实 metadata MCP 与 OpenViking，校准快照/URI 契约；
2. 冲突审计升级为语义/向量级并引入 Owner 抽样复核闭环；
3. 把审计结果入 git 做成可配置开关；
4. 提案增加"半长期事实"队列与自动降级策略；
5. 提供 rules YAML 完整解析依赖并在安装时声明。
