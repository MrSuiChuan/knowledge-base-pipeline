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
"""Paths / IO / git helpers for the knowledge-base-plugin runtime.

Runtime layout inside a user's project after ``/kb-setup``:

    .kb/
      config.json                     # mode(mock|live)、domain、uri_root、owners、audit_level
      _state.json                     # machine state (last audit/publish/generation)
      _context.md                     # state mirror (machine-written)
      mock/
        meta.json                     # mock platform metadata (6 类知识的来源)
      repo/                           # 成品件仓库：git 版本化的知识库内容
        .git/                         # 真实 git（本地版本化，live 可配置 remote）
        .gitignore                    # 审计/待审/驳回文件不入 git
        README.md
        domains/<domain>/navigation.md
        domains/<domain>/skeleton.json
        domains/<domain>/tables/<schema>.<table>.md
        rules/<domain>/<rule_id>.yaml
        proposals/<rule_id>.json
        .kb-manifest.json             # 发布清单（随库提交）
        .kb-audit-*.json              # 审计结果（gitignored）
      ov/                             # mock OpenViking 同步层 (viking://resources/...)
      runtime/
        snapshots/metadata-snapshot-*.json
        .kb-sync-state.json
        hook-logs/*.kb-hook-log.jsonl
        reviews/
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_DIR_NAME = ".kb"
CONFIG_FILE = "config.json"
STATE_FILE = "_state.json"
CONTEXT_MD = "_context.md"
REPO_DIR = "repo"
MOCK_DIR = "mock"
RUNTIME_DIR = "runtime"
OV_DIR = "ov"
SCHEMA_VERSION = 1


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def localnow() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """文件内容的 sha256，**行尾先归一为 LF**。

    不能直接按原始字节哈希：同一份内容在本机（`core.autocrlf=true` 时是 CRLF）与
    新克隆（`.gitattributes` 强制 eol=lf）下字节不同，按字节算会把"没有改动"
    判成"内容变了"。引擎完整性清单与知识树审计都踩过这一类问题。

    引擎与知识文档都很小，整读即可；分块读会有 `\\r\\n` 被切在块边界上的风险。
    """
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def slugify(value: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip())
    return cleaned.strip("-.") or "untitled"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return default


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def load_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def write_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(obj, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def default_config(domain: str = "user") -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "mock",  # mock | live
        "domain": domain,
        "uri_root": "viking://resources/",
        "audit_level": "strict",
        "git_enabled": True,
        "owners": {
            "zhangsan": "张三（用户域 Owner）",
            "lisi": "李四（数据质量 Owner）",
        },
        "limits": {
            "six_layers": 6,
            "spot_checks": 2,
            "max_placeholders_per_manual_doc": 3,
            "rule_proposal_max_age_days": 30,
        },
        "consumer_data_dev_root": "",  # 可选：指向 data-development-plugin 项目根，发布时更新其 mock kb 索引
        "ov": {
            "remote_enabled": False,  # true 表示发布时真实推送到 OpenViking HTTP API
            "url": "",  # OpenViking server，如 http://127.0.0.1:1933
            "api_key_env": "OV_API_KEY",  # 密钥环境变量名（推荐）
            "api_key_file": "",  # 或本地密钥文件路径（首行即密钥，不入 git）
            "account": "",  # 可选：X-OpenViking-Account
            "user": "",  # 可选：X-OpenViking-User
            "timeout": 120,  # 单次 HTTP 请求超时（秒）
            "wait": True,  # content/write 等待语义与向量处理完成
            "scope_readme": False,  # 是否把 repo/README.md 推到 uri_root 的根（共享 scope 建议 False）
            # 会话记忆（与会话记录链路，见 docs/session-memory.md）：
            # commit 会触发 LLM 记忆抽取，走 ov.conf 里的模型配额——所以默认关。
            "memory_enabled": False,
            "keep_recent_count": 10,  # commit 后保留多少条最近消息留在活动会话里
            "task_timeout": 180,  # 后台记忆抽取任务的等待上限（秒）
            # ---- 自动捕获 / 召回（对齐 OpenViking 官方 Codex 插件）----
            # 记忆总开关仍是 memory_enabled；下面两个开关只在总开关打开时生效。
            "auto_capture": True,   # Stop hook：每轮把新对话追加进会话
            "auto_recall": True,    # UserPromptSubmit hook：按 prompt 检索并注入相关记忆
            "capture_mode": "all",  # all | keyword（keyword 只在对话里出现"记住/保存/记录"时捕获）
            "commit_token_threshold": 20000,  # 待提交 token 超过它就自动 commit
            "recall_limit": 6,      # 每次召回最多注入几条
            "recall_timeout_s": 8,  # 召回超时（hook 必须快速返回）
            "session_idle_ttl_minutes": 30,  # SessionStart 清扫：空闲超过它就补捕获并提交
        },
        "created_at": "",
        "updated_at": "",
    }


def project_root(start: Optional[Path] = None) -> Optional[Path]:
    cursor = (start or Path.cwd()).resolve()
    if cursor.is_file():
        cursor = cursor.parent
    for candidate in [cursor, *cursor.parents]:
        if (candidate / APP_DIR_NAME / CONFIG_FILE).is_file():
            return candidate
    return None


def require_project_root(start: Optional[Path] = None) -> Path:
    root = project_root(start)
    if root is None:
        raise FileNotFoundError("未找到 .kb/config.json：请先运行 /kb-setup 初始化 knowledge-base-plugin。")
    return root


def config_path(root: Path) -> Path:
    return root / APP_DIR_NAME / CONFIG_FILE


def load_config(root: Path) -> Dict[str, Any]:
    cfg = load_json(config_path(root), {}) or {}
    merged = default_config(str(cfg.get("domain") or "user"))
    merged.update(cfg)
    ov = dict(default_config("user")["ov"])
    ov.update(cfg.get("ov") or {})
    merged["ov"] = ov
    return merged


def ensure_app_dir(start: Optional[Path] = None, mode: str = "mock", domain: str = "user") -> Path:
    root = (start or Path.cwd()).resolve()
    app = ensure_dir(root / APP_DIR_NAME)
    # 幂等：setup 是可反复跑的入口，重跑只补目录，**不覆盖**已有的 config.json 与 _state.json。
    # 旧实现无条件重写这两份文件，会把用户填的 owners / ov / sources 与
    # last_audit / last_publish / seq 静默清空（版本号还可能因此重复）——
    # 2026-10-14 的插件测试实测踩到（用例 K-02）。
    if not config_path(root).is_file():
        cfg = default_config(domain)
        cfg["mode"] = mode if mode in ("mock", "live") else "mock"
        cfg["created_at"] = utcnow()
        cfg["updated_at"] = utcnow()
        write_json(config_path(root), cfg)
    ensure_dir(app / MOCK_DIR)
    ensure_dir(app / RUNTIME_DIR / "snapshots")
    ensure_dir(app / RUNTIME_DIR / "hook-logs")
    ensure_dir(app / RUNTIME_DIR / "reviews")
    ensure_dir(app / OV_DIR)
    repo = ensure_dir(app / REPO_DIR)
    ensure_dir(repo / "domains")
    ensure_dir(repo / "rules")
    ensure_dir(repo / "proposals")
    ensure_dir(repo / ".kb-pending-review")
    ensure_dir(repo / ".kb-rejected")
    gitignore = repo / ".gitignore"
    if not gitignore.exists():
        write_text(
            gitignore,
            "# knowledge-base-plugin: 审计/待审/驳回产物不入库（协作时需重跑）\n.kb-audit-*.json\n.kb-pending-review/\n.kb-rejected/\n.kb-sync-state.json\n",
        )
    _git_init(repo)
    state_file = root / APP_DIR_NAME / STATE_FILE
    if not state_file.is_file():
        write_json(state_file, default_state(domain))
    return root


def default_state(domain: str) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "domain": domain,
        "last_audit": None,
        "last_publish": None,
        "last_generation": None,
        "last_refresh": None,
        "seq": {"audit": 0, "publish": 0, "proposal": 0},
        "context": {},
    }


def repo_dir(root: Path) -> Path:
    return root / APP_DIR_NAME / REPO_DIR


def domain_dir(root: Path, domain: str) -> Path:
    return repo_dir(root) / "domains" / slugify(domain)


def tables_dir(root: Path, domain: str) -> Path:
    return domain_dir(root, domain) / "tables"


def rules_dir(root: Path, domain: str) -> Path:
    return repo_dir(root) / "rules" / slugify(domain)


def proposals_dir(root: Path) -> Path:
    return repo_dir(root) / "proposals"


def ov_dir(root: Path) -> Path:
    return root / APP_DIR_NAME / OV_DIR


def runtime_dir(root: Path) -> Path:
    return root / APP_DIR_NAME / RUNTIME_DIR


def snapshot_dir(root: Path) -> Path:
    return runtime_dir(root) / "snapshots"


def hook_log_dir(root: Path) -> Path:
    return runtime_dir(root) / "hook-logs"


def state_path(root: Path) -> Path:
    return root / APP_DIR_NAME / STATE_FILE


def load_state(root: Path) -> Dict[str, Any]:
    data = load_json(state_path(root), None)
    if not isinstance(data, dict):
        data = default_state(str((load_config(root) or {}).get("domain", "user")))
    return data


def save_state(root: Path, state: Dict[str, Any]) -> None:
    write_json(state_path(root), state)
    _refresh_context_md(root, state)


def _refresh_context_md(root: Path, state: Dict[str, Any]) -> None:
    lines = [
        "# _context.md — knowledge-base-plugin 状态镜像（机器写入，勿手改）",
        "",
        f"domain={state.get('domain')}",
        f"last_audit={state.get('last_audit')}",
        f"last_publish={state.get('last_publish')}",
        f"last_generation={state.get('last_generation')}",
        f"last_refresh={state.get('last_refresh')}",
        "",
        "## context 键",
        "",
    ]
    for key in sorted((state.get("context") or {}).keys()):
        lines.append(f"{key}={state['context'][key]}")
    lines.append("")
    write_text(root / APP_DIR_NAME / CONTEXT_MD, "\n".join(lines))


def set_state_context(root: Path, key: str, value: Any) -> None:
    state = load_state(root)
    state.setdefault("context", {})[key] = value
    save_state(root, state)


def next_seq(root: Path, key: str) -> int:
    state = load_state(root)
    state.setdefault("seq", {})
    state["seq"][key] = int(state["seq"].get(key, 0)) + 1
    save_state(root, state)
    return state["seq"][key]


def write_audit_file(root: Path, payload: Dict[str, Any]) -> Path:
    path = repo_dir(root) / f".kb-audit-{payload.get('audit_id')}.json"
    write_json(path, payload)
    return path


def latest_audit(root: Path) -> Optional[Dict[str, Any]]:
    audits = sorted(repo_dir(root).glob(".kb-audit-*.json"))
    if not audits:
        return None
    return load_json(audits[-1])


def max_content_mtime(root: Path) -> float:
    newest = 0.0
    for pattern in ("domains/**/*.md", "domains/**/*.json", "rules/**/*.yaml", "proposals/*.json", "README.md"):
        for path in repo_dir(root).glob(pattern):
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                pass
    return newest


def git(path: Path, *args: str) -> Any:
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "找不到 git 可执行文件"}
    return {
        "ok": proc.returncode == 0,
        "rc": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


def _git_init(repo: Path) -> Dict[str, Any]:
    """初始化知识库的本地 git 仓库，并**返回 git 的真实结果**。

    旧实现把 git() 的返回值丢掉了：git 不存在时 /kb-setup 照样报成功，用户以为
    知识库已经版本化了，实际要到发布阶段才会被 git_commit 门拦下。

    提交身份改由 git_commit 用 `-c` 传入，不再写进仓库配置——/kb-setup 每次都要跑
    这一步，少两次子进程。
    """
    if (repo / ".git").is_dir():
        return {"ok": True, "already": True}
    return git(repo, "init", "-q")


def vcs_status(root: Path) -> Dict[str, Any]:
    """版本控制层是否真的可用——给 /kb-setup 在**安装期**报告，而不是等发布时炸。"""
    if not (load_config(root).get("git_enabled", True)):
        return {"ok": True, "enabled": False, "detail": "config.git_enabled=false，已按配置跳过"}
    if shutil.which("git") is None:
        return {
            "ok": False,
            "enabled": True,
            "reason": "找不到 git 可执行文件：知识库不会被版本化，发布会被 git_commit 门拦下。"
            "装好 git 后重跑 /kb-setup。",
        }
    if not (repo_dir(root) / ".git").is_dir():
        return {"ok": False, "enabled": True, "reason": f"{repo_dir(root)} 不是 git 仓库：init 未成功"}
    return {"ok": True, "enabled": True}


GIT_IDENTITY = ("-c", "user.email=knowledge-base-plugin@local", "-c", "user.name=knowledge-base-plugin")


def git_commit(repo: Path, message: str) -> Dict[str, Any]:
    git(repo, "add", "-A")
    result = git(repo, *GIT_IDENTITY, "commit", "-q", "-m", message)
    if not result["ok"] and "nothing to commit" not in result.get("stderr", "") + result.get("stdout", ""):
        return result
    log = git(repo, "log", "-1", "--format=%H")
    return {"ok": True, "sha": log.get("stdout", "")[:40]}


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    ensure_dir(dst.parent)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", ".git"))
