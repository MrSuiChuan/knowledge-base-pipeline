# knowledge-base-plugin 知识库研发规范（由 kb-setup 注入；Codex 读 AGENTS.md）

知识库 = 版本化、可审计、可被 Agent 确定性消费的事实，不是“几篇文档”。

1. 采集铁律：元数据事实只来自平台（mock 元数据源 / live metadata MCP），人只提供业务背景与口径选择；无臆造，每次采集留 `metadata-snapshot.json` 时间锚点。
2. 结构化：按业务骨架（全景→实体过程→场景锚点表→规则→数据层目标）编排；推理纪律 = 场景内全表扫描，严禁因表名跳表。
3. 质检铁律：发布前必须过 `kbp audit --mode publish --level strict`（口径冲突 / 六层断链 / 索引重建），审计不过不许 publish。
4. 审阅责任：机器门禁 APPLIED ≠ Owner 终签；规则 `final_status: READY_FOR_REVIEW` 必须 Owner approve 才 `active`。
5. 沉淀铁律：禁止直接手改 `.kb/repo/rules/`，必走提案（schema/重复/冲突/单测/血缘五道门禁）。
6. 发布双轨：git 入库 + OpenViking 同步缺一不可；guard 门控由 hooks 强制执行。
7. 反哺范围：元数据漂移只自动回灌“基础身份/字段语义”，业务语境/SQL 约束/FAQ 靠人，回灌后必须重跑审计再发布。
8. 状态文件 `.kb/_state.json` / `_context.md` 由引擎写，禁止手改。

入口：`py -3 .kb/engine/kbp.py --help`（Windows）；macOS/Linux 用 `python3`。
