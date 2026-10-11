# 开源就绪审计（按 Apache 项目标准）

**这是一次判断，不是一句自我评价。** 每条给结论与可复核的依据；做不到的如实写"未做/需所有者操作"，
不写"应该没问题"。同一把尺子已在相邻插件 realtime-data-plugin 上用过一轮，本文件按同一口径做。

审计日期：2026-10-07 ｜ 版本基线：`.claude-plugin/plugin.json` 的 `1.2.2`
（本报告对应的改动随 **1.3.0** 发布；复审命令见第八节）

## 一、总览

| 维度 | 结论 |
| --- | --- |
| A 法律与许可 | **通过**：LICENSE 换 Apache-2.0 全文、新增 NOTICE、30 个自研源文件带逐文件许可头、两份清单 license 字段一致 |
| B 流程完整性 | **通过**：治理 / 行为准则 / 支持 / 发版流程 / issue 与 PR 模板 / CODEOWNERS 齐备，且每条都能落地 |
| C 合理性 | **通过**：新增的门（`tools/validate_oss.py`，5 项）在 CI 与用例里真跑；反例用例证明它不是摆设 |
| D 友好性 | **通过**：文档地图、术语表、README 参与与支持、第三方与商标边界 |
| 机器检查 | `python tools/validate_oss.py` **5 项全通过**；`python -m unittest discover -s tests` 全绿（发版时 **111 passed**） |

**需要所有者拍板的一件事**：许可从 MIT 换成 Apache-2.0 是**法律状态变更**（多出明示的专利授权
与声明义务，也多了 NOTICE 与许可头的维护成本）。见第七节。

## 二、A 法律与许可

| # | 检查项 | 结论 | 依据 |
| --- | --- | --- | --- |
| A1 | LICENSE 是 OSI 认可的开源许可全文 | 通过 | `LICENSE` = Apache License 2.0 官方全文（11358 字节），与 realtime-data-plugin 的 LICENSE 逐字节相同（sha256 一致） |
| A2 | 项目名与版权声明 | 通过 | `NOTICE` 写明 `knowledge-base-plugin` / `Copyright 2026 AI实战技能圈` / 许可 |
| A3 | 两份清单的 license 字段 | 通过 | 均为 `Apache-2.0`；`.codex-plugin` 的该字段由生成器从 Claude 清单**一处读**（原先硬编码 `MIT`，换许可时会漂移，已改为单一来源） |
| A4 | 署名三处一致 | 通过 | `NOTICE` 的署名 == 两份清单 `author.name`（`tests/test_repo_invariants.py` 机器核对；Apache-2.0 正文里没有项目署名，故以 NOTICE 为准） |
| A5 | 自研源码逐文件许可头 | 通过 | `engine/` `hooks/` `tools/` `tests/` 共 30 个 `.py`/`.sh` 文件全部带 Apache-2.0 头；`tools/validate_oss.py` 第 4 项会拦新增的漏头文件 |
| A6 | 第三方内容与再分发 | 通过 | 仓库**不含**任何第三方源码/二进制，运行时只用 Python 标准库；边界见 `docs/third-party-dependencies.md` |
| A7 | 名称与商标边界 | 通过 | `NOTICE` 与 `docs/third-party-dependencies.md` 第四节：出现的第三方名称仅用于说明兼容对象与实测事实，不表示赞助或背书 |
| A8 | 贡献授权链条 | 通过 | `CONTRIBUTING.md` 要求 `git commit -s`（DCO），并说明提交即同意以 Apache-2.0 授权 |

## 三、B 流程完整性

| # | 检查项 | 结论 | 依据 |
| --- | --- | --- | --- |
| B1 | 谁能合并、谁能发版 | 通过 | `GOVERNANCE.md`：Owner / Maintainer / Contributor 三角色，明确发版与改许可属 Owner |
| B2 | 决策规则可执行 | 通过 | 惰性共识（3 个自然日）+ 四类"需要更强共识"的事项（改门控语义 / 改许可 / 改对外契约 / 删功能改默认） |
| B3 | 争议升级路径 | 通过 | 先摆事实（命令、输出、期望、实际）→ Owner 裁定 → 理由写回同一 issue |
| B4 | 弃用流程 | 通过 | 标注 `deprecated` + 给替代路径 + 保留至少一个次要版本 + CHANGELOG 写迁移 |
| B5 | 行为准则 | 通过 | `CODE_OF_CONDUCT.md`（参考 Contributor Covenant v2.1 通行做法改写），报告渠道是**真实存在**的入口 |
| B6 | 安全报告路径 | 通过 | `SECURITY.md` 同时覆盖公开期（GitHub Private vulnerability reporting）与私有期（issue / 联系维护者），并给出响应时点 |
| B7 | 支持入口 | 通过 | `SUPPORT.md`：按问题给文档索引、提问要带的四样、明确的支持与非支持范围 |
| B8 | 发版流程 | 通过 | `docs/release-process.md`：6 步可照抄，含"发布后从外部视角核对"与回滚策略 |
| B9 | 参与入口 | 通过 | `.github/ISSUE_TEMPLATE/{bug,feature,config-help}.md` + `config.yml`（关掉空白 issue）+ `PULL_REQUEST_TEMPLATE.md` + `CODEOWNERS` |
| B10 | 版本与变更可追溯 | 通过 | 版本号单一来源（`.claude-plugin/plugin.json`）+ `CHANGELOG.md` + git tag 约定 |

## 四、C 合理性（流程能不能落地）

| # | 检查项 | 结论 | 依据 |
| --- | --- | --- | --- |
| C1 | 文件之间不矛盾 | 通过 | 许可口径四处（LICENSE / NOTICE / 两份清单 / CONTRIBUTING）已对齐，且由 `validate_oss.py` 第 2、3 项机器核对 |
| C2 | 门控不是摆设 | 通过 | `tools/validate_oss.py` 的 5 项都有**反例用例**（缺文件、缺许可头、混进本机路径、清单字段不一致），且挂进 `tests/test_oss_readiness.py` 与 CI |
| C3 | 发版清单可执行 | 通过 | 每条命令都是本仓库真实存在的工具（`build_codex_surface` / `generate_engine_manifest` / `validate_oss` / `adapt_hooks`），并说明"跳步会红在哪" |
| C4 | 模板问的是真需要的信息 | 通过 | bug 模板要 gate 键与完整输出；config 模板列出自检命令；feature 模板问"不做会发生什么"以判优先级 |
| C5 | 不写没人会照做的条款 | 通过 | 治理里每条规则都有触发条件与执行动作（裁定写回 issue、弃用留一个版本），没有"应当保持高质量"这类空话 |
| C6 | 与既有机器门控的关系写清 | 通过 | `GOVERNANCE.md` 末节：治理决定"要不要改门"，不决定"这次能不能绕门" |

## 五、D 友好性

| # | 检查项 | 结论 | 依据 |
| --- | --- | --- | --- |
| D1 | 新人能快速跑起来 | 通过 | README「快速开始」+ `demo` 一条命令出成品；非 Windows 的 hook 适配在 README/CONTRIBUTING/SUPPORT 三处都点到 |
| D2 | 文档有索引 | 通过 | `docs/README.md` 按"你手上是什么问题"组织，并标注哪些是过程记录而非教程 |
| D3 | 术语有解释 | 通过 | `docs/glossary.md` 14 个本仓库特定含义的词 + 4 条常见误解 |
| D4 | 报错指向下一步 | 通过 | 门控返回 gate 键与可读原因（如 `source_config_missing` 直接列出缺哪些键）；新增自检逐条写"缺什么、去哪儿补" |
| D5 | 边界与未验证之处写清 | 通过 | SECURITY 的 Known limits、glossary 的常见误解、`docs/realtime-sources.md` 的边界一节；"未验证"是结论不是客气话 |

## 六、本轮落地的改动

| 维度 | 落地 |
| --- | --- |
| 许可 | `LICENSE` 换 Apache-2.0 全文；新增 `NOTICE`；30 个自研源文件加逐文件许可头；两份清单 `license` 字段；`CONTRIBUTING` 的 License 段与 DCO；生成器改为从 Claude 清单一处读 `author`/`license` |
| 治理 | 新增 `GOVERNANCE.md`、`CODE_OF_CONDUCT.md`、`SUPPORT.md`、`docs/release-process.md` |
| 入口与安全 | 新增三个 issue 模板 + `config.yml` + PR 模板 + `CODEOWNERS`；`SECURITY.md` 改为覆盖公开期与私有期，并给出响应时点 |
| 友好性 | 新增 `docs/README.md`（文档地图）、`docs/glossary.md`（术语表）；README 补「参与与支持」并改 License 段；README.en.md 对齐 |
| 第三方边界 | 新增 `docs/third-party-dependencies.md`（仓库内包含什么 / 测试时在谁的机器上跑什么 / 商标）；`NOTICE` 与之口径一致 |
| 机器检查 | 新增 `tools/validate_oss.py`（5 项）+ `tests/test_oss_readiness.py`（1 正例 + 3 反例）；CI 新增该步 |
| 脱敏 | 清掉 `docs/realtime-sources.md` 与台账里的维护者本机路径；个人路径纳入自检 |

## 七、需要所有者决策 / 未完成（如实留白）

1. **许可从 MIT 换成 Apache-2.0**：这是法律状态变更，不是技术选择。已按"Apache 标准 +
   与另两个插件口径一致"落地。若你想保留 MIT，回滚点是：`LICENSE`、`NOTICE`、
   两份 `plugin.json` 的 `license`、`CONTRIBUTING` 的 License 段、以及 `validate_oss.py` 的
   第 2/3 项与 `tests/test_repo_invariants.py` 的对应断言——六处要一起改。
2. **GitHub 侧设置只能在网页后台做，本机做不到**：
   - 打开 **Settings → Security → Private vulnerability reporting**（`SECURITY.md` 的公开期路径依赖它）；
   - 确认 `CODEOWNERS`（`@MrSuiChuan`）是有效账号、按需开分支保护；
   - 仓库当前是**私有**（2026-10-07 匿名访问实测 404）；何时公开是你的决定。
3. **全历史扫描范围**：本轮扫了 14 个提交的全部 patch，命中仅一处
   `self.api_key = str(settings["api_key"])`——那是从环境变量/密钥文件读取，**不是硬编码密钥**。
   扫描是文本级（正则），不是熵检测；若有二进制对象需要另行核对。
4. **未做**：英文版治理类文档（`GOVERNANCE` / `CODE_OF_CONDUCT` / `SUPPORT` 目前只有中文，
   `README.en.md` 已给出索引）；如果你要求对外英文材料齐备，这是一项新工作。

## 八、怎么复核这份报告

```bash
py -3 tools/validate_oss.py                 # 5 项机器检查（本报告 A/B/C/D 的机器可判定部分）
py -3 -m unittest discover -s tests         # 全量用例（含 test_oss_readiness 的正例与反例）
git log --all --patch | rg -i "sk-[A-Za-z0-9]{12,}|api[_-]?key\s*[:=]"   # 全历史密钥样式扫描
git ls-files -z | xargs -0 rg -n "C:\\\\Users|/home/[a-z][a-z0-9_-]*/"   # 个人路径（应当只命中豁免文件）
```
