# Contributing

Thanks for considering a contribution to knowledge-base-plugin.

## Development loop

```bash
python -m unittest discover -s tests   # unit + demo tests
python -m compileall -q engine hooks tests tools
python tools/validate_oss.py           # 开源标准：文件齐全 / 许可头 / 清单字段 / 无个人路径
claude plugin validate .
```

> 非 Windows 机器上装完插件后还必须跑一次 `python tools/adapt_hooks.py`
> （`--check` 用来体检）：hook 启动器不存在时宿主会把失败当放行，审计门与发布门会静默失效。

## Rules

- `.kb/` runtime state is machine-owned; never commit `.kb/` content.
- Proposal/rules changes must go through the proposal gate, never by editing
  `rules/` directly (hooks enforce this).
- Audit results stay local by default; keep that contract documented.
- Add regression tests for gate/validator changes.
- Keep the Python floor honest: the minimum version comes from the `Python X.Y+`
  line in `README.md`, and `.github/workflows/ci.yml` must run the full suite on
  that version (`tests/test_repo_invariants.py` checks both, and also parses every
  source file with that version's grammar).
- After changing anything under `engine/`, run `python tools/generate_engine_manifest.py`
  — `kbp.py` verifies `.kb/engine` against that baseline on every boot, and
  `tests/test_repo_invariants.py` fails when the baseline is stale.
- After changing anything under `commands/`, run `python tools/build_codex_surface.py`
  — `tests/test_generated_surface.py` compares the output byte for byte.
- The base version lives in `.claude-plugin/plugin.json` only; `.codex-plugin`
  derives it (plus the `+codex.<token>` cachebuster from `tools/reinstall.py`), and
  `CHANGELOG.md` must have a matching latest released section.
- Hash files with `context.sha256_file`, never with raw bytes: it normalizes line
  endings to LF first. Raw-byte hashing breaks engine integrity and audit freshness
  across CRLF/LF checkouts (both were real bugs here).

## License

Apache-2.0 — see [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。

提交即表示你同意以 Apache-2.0 授权你的贡献，并按
[Developer Certificate of Origin](https://developercertificate.org/) 声明你有权提交它：

```bash
git commit -s        # 会带上一行 Signed-off-by
```

## Pull Request 需要什么

1. **能复现的说明**：改了什么、为什么、怎么验证的（命令 + 关键输出，不是"测试通过"四个字）；
2. **先失败后通过的用例**：改门控 / 校验器 / 哈希这类地方，用例必须是"改之前红、改之后绿"；
3. **同步产物**：改 `engine/` 跑清单生成器，改 `commands/` 跑 Codex 面生成器
   （见上面的 Rules 一节）；
4. **写进 CHANGELOG**：对使用者可见的改动，在 `[Unreleased]` 里加一条；
5. **不夹带**：一次 PR 一件事；顺手发现的问题另开 issue 或另开 PR。

评审规则与争议升级见 [GOVERNANCE.md](GOVERNANCE.md)；行为要求见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
