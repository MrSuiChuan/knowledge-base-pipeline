# Security

## 怎么报告漏洞

**仓库公开后（目标状态）**：走 GitHub 的 **Private vulnerability reporting** ——
仓库 **Security** 标签页里的 **Report a vulnerability**。维护者需要在
**Settings → Security** 里先打开这个功能（Advanced Security 才提供该入口）。

**仓库还是私有的期间（当下）**：私有仓库**没有**那个入口，所以：

- 你有仓库权限 → 开一个 issue、打上 `security` 标签，贴最小复现；
- 你没有权限 → 联系维护者 `@MrSuiChuan`。

> 维护者须知：这一段在 2026-09-21 前后被改坏过两次——第一次指向"marketplace 元数据里的
> 邮箱"（两个清单里根本没有这个字段），第二次指向 GitHub 私密报告（当时仓库是私有的，
> 那个入口不存在）。**改这一块之前先确认入口真的存在，不要照着习惯写。**

## 响应预期

| 阶段 | 时点 |
| --- | --- |
| 初次回应（收到报告） | 7 个自然日内 |
| 初步判定（是否成立、影响面） | 14 个自然日内 |
| 修复或缓解方案 | 判定成立后按严重度排期；高风险优先出补丁版本 |

修复发布后会在 `CHANGELOG.md` 写明影响面与升级动作；报告者若愿意，会在发布说明里署名致谢。
**支持范围**：`main` 上的最新发布版本。更早的版本不单独回补，除非影响面很大。

## Security model（三层防线的强度不一样，请分清）

| 层 | 机制 | 强度 |
| --- | --- | --- |
| 宿主 hook（PreToolUse） | 拦截：未审计发布/同步、`.kb/runtime` 与 `_state.json` 等机器资产、`rules/` 直改 | **提高作弊成本**，不是沙箱 |
| 引擎内门控 | `engine/kbp.py` 每个动词先跑 `gates`；publish / ov-sync / propose 必须经引擎 | 与宿主无关，AI 绕不开 |
| 留证与交叉核验 | `.kb-audit-*.json`（含 `content_hash`）+ `.kb-manifest.json` / sync-state，发布前重算比对 | **证据可信度的真正来源** |

一句话：hook 负责"让偷懒变贵"，审计留证 + 内容哈希负责"让撒谎不可能"
（篡改 `_state.json` 说审计已过，也会被 `content_hash` 比对挡下）。

## Known limits / non-goals（对抗式验收后如实记录）

1. **hook 的命令判定是启发式，不是 shell 解释器。** 它按分隔符切段、展开简单变量、
   识别 `cd` 进入 `.kb/runtime` 等写法。下面这些原本被列为"可绕过"，**实测已经被拦住**，
   并且 `tests/test_known_limits.py` 会一直盯着它们不再回退：

   `& $c` 间接调用 · 环境变量拼路径 · 变量拼接出路径 · 从别的目录写回受保护位置 ·
   管道写出 · 整条命令放进变量再 `iex` · 直改 `rules/`（`rules_direct_write_guard`）

   **仍然开着的口子只剩一个**：把写操作放进一个脚本文件、再执行那个脚本——hook 只看得见
   宿主暴露的那条命令，看不见脚本内容。**不要把它当作安全边界。**
2. **hook 只能看到宿主暴露的工具调用。** 子进程内部副作用（自行连 OpenViking/git、
   访问网络、写宿主看不到的位置）不在覆盖内；真正的闸门是 OpenViking / git 侧的凭证与权限。
3. **APPLIED 与 REVIEWED 是两个时间轴**（见 Design notes）。机器门禁通过不等于 Owner 终签；
   这段窗口是已知治理缺口，靠流程约束而不是靠 hook 兜底。
4. **非目标：不是沙箱、不是权限系统、不校验 OpenViking/上游平台的信任模型。**
   生产使用建议：`OV_API_KEY` 等凭证只放运行环境、按域划分仓库权限、
   发布走 `[已审计→已终签→发布]` 的人工闭环、在容器/虚拟机中运行 Agent。

Design notes:
- `.kb/repo/rules/**` is write-protected: rules must be proposed and approved.
- Publish requires a fresh strict audit (`audit_completion_guard`).
- OpenViking/git credentials belong to the runtime environment, not the repo.
- The APPLIED→REVIEWED window is a known governance gap: keep Owner approval in
  the loop and do not auto-approve proposals.
