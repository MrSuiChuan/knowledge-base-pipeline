# knowledge-base-plugin

A **dual-host** plugin (Claude Code **and** Codex) that turns data-warehouse
knowledge maintenance into a gated, versioned pipeline. Both hosts share one
engine and one set of hooks:

```text
collect → structure → audit → review → publish → refresh → grow
```

Every step is backed by machine checks and artifacts:

- Collect: 6 metadata categories from platform MCP or the mock source; no
  snapshot, no generation.
- Structure: five-step business skeleton with scenario anchor tables.
- Audit: conflict / link / index checks; publish requires a fresh strict audit.
- Review: Owner approval; proposals never auto-approve.
- Publish: git commit/tag + OpenViking sync (configurable `uri_root`).
- Refresh: metadata-driven backfill of identity/column sections.
- Grow: long-lived facts enter through a five-gate proposal flow.

## Install (short version)

1. Install the plugin from a marketplace — see the Chinese [README.md](README.md)
   for both hosts (`/kb-setup` … on Claude Code, `kbp-*` skills on Codex).
2. `/kb-setup` copies the engine into `.kb/engine`; `kbp.py` then verifies that
   copy against `engine/.engine-manifest.json` on every run and refuses to continue
   if it does not match.
3. **On macOS/Linux, run `python3 tools/adapt_hooks.py` once.** The committed hook
   commands use the Windows launcher `py -3`; without adapting, every hook command
   fails, the host fails *open*, and the audit/publish gates silently stop working.
   `python3 tools/adapt_hooks.py --check` reports whether this machine is OK.

This plugin is the upstream of `data-development-plugin`: it publishes to
`viking://resources/`, and that plugin's SDS phase only consumes knowledge under
that prefix. The handoff between them is covered by contract tests on both sides.

## Docs

The Chinese docs are authoritative; this page is a summary.

- [README.md](README.md) — full setup, connectors, publishing
- [docs/README.md](docs/README.md) — documentation map (start here if unsure)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — runtime layout, gates
- [docs/glossary.md](docs/glossary.md) — terms that mean something specific here
- [SECURITY.md](SECURITY.md) — security model and **known limits** (read this one)
- [CONTRIBUTING.md](CONTRIBUTING.md) — dev loop and the checks CI enforces
- [GOVERNANCE.md](GOVERNANCE.md) / [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) / [SUPPORT.md](SUPPORT.md)
- [docs/release-process.md](docs/release-process.md) — how a release is cut
- [docs/apache-readiness-audit.md](docs/apache-readiness-audit.md) — open-source readiness audit
- [CHANGELOG.md](CHANGELOG.md)

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
