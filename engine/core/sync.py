# Copyright 2026 AI实战技能圈
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""发布层：git 入库 + OpenViking 同步（双轨），带 guard 门控。

产物：.kb-manifest.json（随库提交）、.kb-sync-state.json（运行态，gitignore）、
*.kb-hook-log.jsonl（门控日志）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import audit, context, ov_remote


def _uri_prefix(config: Dict[str, Any]) -> str:
    prefix = str((config or {}).get("uri_root") or "viking://resources/").rstrip("/")
    return prefix + "/"


def _collect_files(root: Path, domain: str) -> List[tuple]:
    """把 repo 内容映射为 ``(uri, content)`` 清单（本地镜像与远端推送共用）。"""
    prefix = _uri_prefix(context.load_config(root))
    files: List[tuple] = []
    domain_rel = context.domain_dir(root, domain).relative_to(context.repo_dir(root))
    for path in sorted(context.domain_dir(root, domain).rglob("*")):
        if path.is_file():
            rel = (domain_rel / path.relative_to(context.domain_dir(root, domain))).as_posix()
            files.append((f"{prefix}{rel}", context.read_text(path)))
    for path in sorted(context.rules_dir(root, domain).glob("*.yaml")):
        rel = (context.rules_dir(root, domain).relative_to(context.repo_dir(root)) / path.name).as_posix()
        files.append((f"{prefix}{rel}", context.read_text(path)))
    readme = context.repo_dir(root) / "README.md"
    if readme.is_file():
        files.append((f"{prefix}README.md", context.read_text(readme)))
    return files


def collect_uris(root: Path, domain: str) -> List[str]:
    """把 repo 内容映射为 viking://resources/ 下的 URI 清单。"""
    return [uri for uri, _ in _collect_files(root, domain)]


def sync_to_ov(root: Path, domain: str) -> List[str]:
    """把已发布内容同步到 mock/live OpenViking 层。返回写入的 URI。"""
    ov = context.ov_dir(root)
    prefix = _uri_prefix(context.load_config(root))
    uris: List[str] = []
    for uri, content in _collect_files(root, domain):
        uris.append(uri)
        rel = uri[len(prefix):] if uri.startswith(prefix) else uri.split("/")[-1]
        dst = ov / rel
        context.write_text(dst, content)
    # 建立 viking 索引（mock OV 的“对 Agent 可见”）
    index_path = ov / "index.json"
    index = context.load_json(index_path, {"documents": []})
    known = {d.get("uri") for d in index.get("documents", [])}
    for uri in uris:
        if uri not in known:
            index.setdefault("documents", []).append({"uri": uri, "domain": domain, "synced_at": context.utcnow()})
    context.write_json(index_path, index)
    return uris


def publish(root: Path, domain: str, reason: str = "", consumer_root: Optional[Path] = None) -> Dict[str, Any]:
    """发布门（引擎侧也执行 guard；hook 侧在 PreToolUse 再做一次）。"""
    gate = audit.audit_fresh_enough(root)
    if not gate["ok"]:
        return {"ok": False, "blocked": True, "gate": "kb_publish_guard", "reason": gate["reason"]}
    config = context.load_config(root)
    ov_cfg = config.get("ov") or {}
    remote_enabled = bool(ov_cfg.get("remote_enabled"))
    if (config.get("mode") or "mock") == "live" and not remote_enabled:
        return {
            "ok": False,
            "blocked": True,
            "gate": "ov_live_not_configured",
            "reason": "mode=live 但未配置真实 OpenViking 同步器（ov.remote_enabled=false）："
            "当前不会真的发布到远端；请先启用 ov.remote_enabled 并配置 ov.url / 密钥，"
            "或改回 mock/local 模式。",
        }
    repo = context.repo_dir(root)
    # 远端推送先于 git 提交：远端失败时不留下“已 tag 但未上云”的假成功状态
    remote_result = None
    if remote_enabled:
        remote_files = _collect_files(root, domain)
        prefix = _uri_prefix(config)
        scope_readme_uri = f"{prefix}README.md"
        if not bool((config.get("ov") or {}).get("scope_readme")):
            # 共享 scope 时禁止用本仓 README 覆盖 uri_root 根文档；本地镜像仍保留
            remote_files = [(u, c) for u, c in remote_files if u != scope_readme_uri]
        remote_result = ov_remote.push_files(config, remote_files)
        if not remote_result.get("ok"):
            reason = remote_result.get("reason") or f"远端同步失败: code={remote_result.get('code')}"
            _log_hook(
                root,
                "publish",
                {
                    "ok": False,
                    "domain": domain,
                    "gate": "ov_remote_sync",
                    "reason": reason,
                    "remote": {k: remote_result.get(k) for k in ("code", "server", "configured", "failed")},
                },
            )
            return {
                "ok": False,
                "blocked": True,
                "gate": "ov_remote_sync",
                "reason": reason,
                "remote": remote_result,
            }
    version_seq = context.next_seq(root, "publish")
    version = f"kb-v{version_seq}"
    commit_result = {"ok": True, "sha": ""}
    if context.load_config(root).get("git_enabled", True):
        commit_result = context.git_commit(repo, f"publish {version} ({domain}): {reason}")
        if not commit_result["ok"]:
            return {"ok": False, "blocked": True, "gate": "git_commit", "reason": commit_result.get("stderr", "git commit 失败")}
        context.git(repo, "tag", "-f", version)
    else:
        # git 关闭时用内容哈希做版本锚（mock 场景）
        commit_result["sha"] = context.sha256_text(str(sorted(context.read_text(p) for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts)))[:16]
    uris = sync_to_ov(root, domain)
    manifest_path = repo / ".kb-manifest.json"
    manifest = context.load_json(manifest_path, {"publishes": []})
    entry: Dict[str, Any] = {
        "version": version,
        "domain": domain,
        "commit": commit_result.get("sha", ""),
        "uris": uris,
        "ov_sync": "remote" if remote_enabled else "local-mirror",
        "reason": reason,
        "at": context.utcnow(),
    }
    if remote_result:
        entry["remote"] = {
            "server": remote_result.get("server", ""),
            "pushed": len(remote_result.get("pushed", [])),
            "verified": remote_result.get("verified", 0),
        }
    manifest.setdefault("publishes", []).append(entry)
    context.write_json(manifest_path, manifest)
    if context.load_config(root).get("git_enabled", True):
        context.git(repo, "add", "-A")
        context.git(repo, "commit", "-q", "-m", f"manifest {version}")
    sync_state: Dict[str, Any] = {
        "last_version": version,
        "last_commit": commit_result.get("sha", ""),
        "ov_synced_at": context.utcnow(),
        "ov_sync": "remote" if remote_enabled else "local-mirror",
        "uris": uris,
    }
    if remote_result:
        sync_state["remote"] = {
            "server": remote_result.get("server", ""),
            "pushed": len(remote_result.get("pushed", [])),
            "verified": remote_result.get("verified", 0),
        }
    context.write_json(context.runtime_dir(root) / ".kb-sync-state.json", sync_state)
    _log_hook(root, "publish", {"ok": True, "version": version, "domain": domain})
    state = context.load_state(root)
    state["last_publish"] = {"version": version, "at": entry["at"], "reason": reason}
    context.save_state(root, state)
    consumer_sync: Optional[Dict[str, Any]] = None
    if consumer_root is not None or context.load_config(root).get("consumer_data_dev_root"):
        target = consumer_root or Path(context.load_config(root)["consumer_data_dev_root"])
        consumer_sync = _update_data_dev_index(root, target, domain)
        # 不把消费方同步失败当成发布失败：git 提交与 OV 同步确实成功了，为此回滚只会
        # 制造第二个 commit。但它必须**可见**——原来这个返回值被直接丢掉，消费方还没
        # 初始化时同步一行都没做，调用方却只看到 ok:true（实测）。
        _log_hook(root, "consumer-sync", consumer_sync)
    return {
        "ok": True,
        "version": version,
        "commit": commit_result.get("sha"),
        "uris": uris,
        "consumer_sync": consumer_sync,
    }


def _log_hook(root: Path, event: str, payload: Dict[str, Any]) -> None:
    path = context.hook_log_dir(root) / f"{event}.kb-hook-log.jsonl"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": event, "at": context.utcnow(), **payload}, ensure_ascii=False) + "\n")


def _update_data_dev_index(root: Path, consumer_root: Path, domain: str) -> Dict[str, Any]:
    """把发布结果同步给 data-development-plugin 的 mock 知识库索引（跨插件契约）。"""
    kb_index = consumer_root / ".data-dev" / "mock" / "kb" / "index.json"
    if not kb_index.exists():
        return {"ok": False, "reason": f"consumer 无 data-development-plugin kb 索引: {kb_index}"}
    index = context.load_json(kb_index, {"documents": []})
    known = {d.get("uri") for d in index.get("documents", [])}
    prefix = _uri_prefix(context.load_config(root))
    added = []
    for doc_path in sorted(context.domain_dir(root, domain).glob("tables/*.md")):
        uri = f"{prefix}domains/{domain}/tables/{doc_path.name}"
        if uri in known:
            continue
        text = context.read_text(doc_path)
        abstract_lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#") and not ln.startswith(">")]
        table_id = doc_path.stem
        index.setdefault("documents", []).append(
            {
                "uri": uri,
                "domain": domain,
                "layer": table_id.split("_")[0],
                "tables": [table_id],
                "abstract": (abstract_lines[0] if abstract_lines else "")[:200],
            }
        )
        added.append(uri)
    context.write_json(kb_index, index)
    return {"ok": True, "added": added}
