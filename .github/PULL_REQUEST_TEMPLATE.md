# 改了什么

<!-- 一句话说清这次改动要解决的问题。 -->

## 怎么验证的

<!-- 光说"测试通过"不算：贴命令与关键输出。改门控/校验器时，必须有一条"先失败、后通过"的用例。 -->

```bash
python -m unittest discover -s tests
python tools/validate_oss.py
```

## 检查清单

- [ ] 改了 `engine/` → 跑过 `python tools/generate_engine_manifest.py`
- [ ] 改了 `commands/` → 跑过 `python tools/build_codex_surface.py`
- [ ] 改了行为 → `CHANGELOG.md` 的 `[Unreleased]` 有对应条目
- [ ] 新增/修改了机器资产（`.kb/` 状态、审计、清单）→ 有对应回归用例
- [ ] 新文件带 Apache-2.0 许可头（`python tools/validate_oss.py` 会拦）
- [ ] 没把密钥、内网地址、本机路径、真实数据写进来

## 关联

<!-- 关联 issue / 台账项编号（KBP-xxx）。 -->
