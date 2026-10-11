# 发版流程

按顺序做，每一步都有可核对的产物。**不要跳步**——本项目里"跳步"的具体后果是
引擎清单或 Codex 面与源码不一致，而这两处在 CI 里是红的（历史上各踩过一次）。

## 0. 前置

- `main` 工作区干净，CI 全绿；
- 本次要发的改动都已在 `CHANGELOG.md` 的 `[Unreleased]` 里写清。

## 1. 定版本

版本号只在 **`.claude-plugin/plugin.json`** 里维护（唯一版本源）。

1. 改 `version`（语义化版本：对外行为变 → minor；只修缺陷 → patch）；
2. `CHANGELOG.md`：把 `[Unreleased]` 改成本次的 `## [x.y.z] - YYYY-MM-DD`，
   并新开一个空的 `[Unreleased]`；
3. 重生成 Codex 面（它会派生 `.codex-plugin/plugin.json` 并保留 `+codex.<token>` 后缀）：

```bash
python tools/build_codex_surface.py
```

## 2. 重生成带哈希的产物

```bash
python tools/generate_engine_manifest.py     # engine/ 任何改动之后必须跑
```

## 3. 本地验收（四项都过才算）

```bash
python -m unittest discover -s tests        # 全量用例
python -m compileall -q engine hooks tests tools
python tools/validate_oss.py                # 开源标准：文件齐全 + 许可头 + 清单字段一致 + 无个人路径
python tools/adapt_hooks.py --check         # hook 启动器在本机可用
```

> `tools/adapt_hooks.py` 不是发版动作，是**安装动作**：非 Windows 机器上装完必须跑一次
> `python tools/adapt_hooks.py`，否则 hook 启动器不存在，宿主会把失败当放行。

## 4. 打 tag 并推送

```bash
git tag -a vx.y.z -m "knowledge-base-plugin vx.y.z"
git push origin main --tags
```

## 5. 发布后核对（从外部视角，不是从本机）

1. 新克隆一份：`git clone <repo> && cd knowledge-base-plugin`；
2. 跑 mock 全流程：`python -m unittest discover -s tests`；
3. 装到宿主后跑一次 `demo`，确认 `.kb/repo/.kb-manifest.json` 里有 `kb-v1`/`kb-v2`；
4. 核对 GitHub Release 说明与 `CHANGELOG.md` 的该版本小节一致。
5. **同步公开镜像**（见第 7 节）：`py -3 tools/publish_public.py --check` 通过后
   再 `--apply`；建议从公开仓库新鲜克隆一份跑一次全量用例，确认发出去的是能跑的仓库。

## 6. 回滚

- **已推的 tag 不改写**（改写别人的克隆会炸）；发一个 patch 版本修问题；
- 若发布物本身不可用（例如清单版本号与 tag 不一致），在 Release 说明顶部加显著提示，
  并把修复版本作为 latest。

## 7. 公开镜像同步（私有主干 → 公开仓库）

本仓库有两个面：**私有主干**（日常开发，含内网地址与账号细节）与**公开镜像**
`MrSuiChuan/knowledge-base-pipeline`。镜像不是一个分支，而是**从当前提交生成的脱敏快照**：

```bash
py -3 tools/publish_public.py --check     # 只读：替换统计 + 残留检查（残留即失败）
py -3 tools/publish_public.py --apply     # 生成快照 → 提交 → 推送公开仓库
```

替换表（字面量、长的在前）与理由：

| 私有内容 | 公开写法 | 为什么 |
| --- | --- | --- |
| 线上实例的 IP 与端口 | `<openviking-host>` | 内网/公网地址不对外 |
| 主机名 | `<host>` | 同上 |
| 账号 / 用户 / 租户名 | `<account>` / `<user>` | 内部标识 |
| 密钥文件、SSH 私钥路径 | `<key-file>` / `<ssh-key-file>` | 只留形状，不留位置 |
| 本机工作区路径 | `<workspace>` | 本机布局 |

**唯一豁免**是 `.github/workflows/ci.yml` 里那行"禁止出现的词"列表——它列的正是这些要被挡住的词，
把这行也替换掉，检测就形同虚设。`--check` 的残留检查会放行该文件、拦住其它任何残留。

三条纪律：

1. 快照只取 `git ls-files` 的**跟踪文件**，本机运行时产物（`.tmp/`、`.kb/`、`.data-dev/`）不出去；
2. `--check` 不通过就**不许推**（`--apply` 会自己先跑一遍 check，失败即中止）；
3. 两边内容必须一致——所以不存在"公开版改了但私有版没改"这种漂移；要改就改主干再同步。

## 附：这一节的血泪来源

- 生成物漂移（KBP-003）：`.codex-plugin/plugin.json` 曾是 `\uXXXX` 转义，与生成器输出不一致，没人发现；
- 引擎清单陈旧（KBP-002）：改过 `engine/` 却没重算清单，`.kb/engine` 的自检就形同虚设；
- 许可头与清单字段（KBP-027）：从 MIT 换 Apache-2.0 时，`LICENSE`、`NOTICE`、
  两份 `plugin.json`、`CONTRIBUTING` 四处必须一起改，漏一处就是自相矛盾。
