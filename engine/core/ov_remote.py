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
"""OpenViking HTTP 传输器（真实远端发布）。

与 OpenViking server 0.4.x 的 HTTP API 直接对话：

    GET  /api/v1/fs/stat      判断目录/文件是否存在
    POST /api/v1/fs/mkdir    创建父目录
    POST /api/v1/content/write 写入/创建文件（mode=replace|create，wait）
    GET  /api/v1/content/download  字节级回读校验（不信任"写入成功"）

鉴权：``X-API-Key``（或 ``Authorization: Bearer``），可选
``X-OpenViking-Account`` / ``X-OpenViking-User``。

只使用标准库（urllib / json），不引入第三方依赖；任何失败都以结构化错误
返回，绝不伪造成功——远端未写完 = publish 被硬阻断。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


class OVConfigError(RuntimeError):
    """配置缺失/非法（URL、API Key 未就绪）。"""


class OVRemoteError(RuntimeError):
    """OpenViking 服务端或传输层错误。"""

    def __init__(self, code: str, message: str, uri: str = "", details: Any = None, http_status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.uri = uri
        self.details = details
        self.http_status = http_status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "uri": self.uri or None,
            "http_status": self.http_status or None,
        }


def validate_uri(uri: str) -> str:
    """只允许 ``viking://<scope>/...`` 形态的 URI。"""
    text = str(uri or "").strip()
    if not text.startswith("viking://"):
        raise OVRemoteError("invalid_uri", f"非法 Viking URI: {text!r}", uri=text)
    if "/" not in text[len("viking://"):]:
        raise OVRemoteError("invalid_uri", f"Viking URI 缺少路径: {text!r}", uri=text)
    return text


def parent_dirs(uri: str, include_scope_root: bool = False) -> List[str]:
    """返回某个文件 URI 的全部父目录（从 scope 根到直接父目录）。"""
    text = validate_uri(uri)
    _, _, rest = text.partition("://")
    parts = [p for p in rest.split("/") if p]
    if len(parts) < 2:
        return []
    dirs: List[str] = []
    for i in range(1, len(parts)):
        prefix = "viking://" + "/".join(parts[:i])
        if i == 1 and not include_scope_root:
            continue
        dirs.append(prefix)
    return dirs


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def is_local_url(url: str) -> bool:
    """判断是不是本机地址（本机 OpenViking 常用 dev 模式，不需要鉴权）。"""
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return False
    return host.lower() in LOCAL_HOSTS


def _ovcli_conf() -> Dict[str, Any]:
    """读 ``~/.openviking/ovcli.conf``（官方 ``ov`` CLI 的配置）。

    作为 ``ov.url`` / ``api_key`` / ``account`` / ``user`` 的回退：官方 Codex 插件就是
    从这份文件取连接的。读不到或解析失败一律返回空字典，不影响项目级配置。
    """
    from pathlib import Path as _Path

    configured = os.environ.get("OPENVIKING_CLI_CONFIG_FILE", "").strip()
    try:
        path = _Path(configured) if configured else _Path.home() / ".openviking" / "ovcli.conf"
    except (RuntimeError, OSError):
        # 测试里会 clear 掉 HOME/USERPROFILE；取不到家目录就当没有这份配置。
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """从 config.json 的 ``ov`` 段解析传输参数。

    Key 只从环境变量（``api_key_env``，默认 ``OV_API_KEY``）或本地密钥文件
    （``api_key_file``，文件首行，不进入 config.json / manifest）读取，避免密钥
    落盘到 git 可见的配置文件。
    """
    ov = config.get("ov") or {}
    cli_conf = _ovcli_conf()
    url = str(ov.get("url") or "").strip().rstrip("/")
    if not url:
        # 与 OpenViking 官方 Codex 插件对齐：项目配置没写 url 时，回退读
        # ~/.openviking/ovcli.conf（`ov` CLI 用的那份）。这样"只配了 ovcli.conf"
        # 的用户不会看到插件说"缺 ov.url"（2026-10-17 实测踩到）。
        url = str(cli_conf.get("url") or "").strip().rstrip("/")
    if not url:
        raise OVConfigError(
            "缺少 ov.url：请在 .kb/config.json 配置 OpenViking 服务地址"
            "（或写 ~/.openviking/ovcli.conf 的 url）"
        )
    if not url.startswith(("http://", "https://")):
        raise OVConfigError(f"ov.url 必须是 http(s):// 地址: {url!r}")

    key = ""
    env_name = str(ov.get("api_key_env") or "OV_API_KEY").strip()
    key = os.environ.get(env_name, "").strip()
    if not key:
        key_file = str(ov.get("api_key_file") or "").strip()
        if key_file:
            try:
                with open(key_file, "r", encoding="utf-8") as handle:
                    key = handle.read().strip().splitlines()[0].strip()
            except (OSError, IndexError) as exc:
                raise OVConfigError(f"读取 ov.api_key_file 失败: {key_file}: {exc}") from exc
    if not key:
        key = str(cli_conf.get("api_key") or "").strip()
    if not key and not is_local_url(url):
        raise OVConfigError(
            f"缺少 API Key：请设置环境变量 {env_name}（或配置 ov.api_key_file 指向本地密钥文件）"
        )
    # 本地地址允许空 key：本机 OpenViking 是 dev 模式（服务端 server/auth.py 写着
    # "Dev mode: no authentication, always return ROOT"），本机 ovcli.conf 里也没有密钥。
    # 若这里硬要 key，本地部署会变成"装好即不可用"（2026-10-11 实测）。
    if key and len(key) < 8:
        raise OVConfigError("ov API Key 长度异常（<8 字符），请检查密钥来源")

    try:
        timeout = float(ov.get("timeout") or 120)
    except (TypeError, ValueError):
        timeout = 120.0
    return {
        "url": url,
        "api_key": key,
        "account": str(ov.get("account") or cli_conf.get("account") or "").strip(),
        "user": str(ov.get("user") or cli_conf.get("user") or "").strip(),
        "timeout": timeout,
        "wait": bool(ov.get("wait", True)),
    }


def _parse_error(raw: bytes, http_status: int, uri: str = "") -> OVRemoteError:
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        err = (payload or {}).get("error") or {}
        code = str(err.get("code") or f"HTTP_{http_status}")
        message = str(err.get("message") or raw.decode("utf-8", errors="replace")[:300])
        return OVRemoteError(code, message, uri=uri, details=err.get("details"), http_status=http_status)
    except Exception:
        text = raw.decode("utf-8", errors="replace")[:300]
        return OVRemoteError(f"HTTP_{http_status}", text or f"HTTP {http_status}", uri=uri, http_status=http_status)


class RemoteClient:
    """面向 OpenViking HTTP API 的极简客户端。"""

    def __init__(self, settings: Dict[str, Any]) -> None:
        self.base_url = str(settings["url"]).rstrip("/")
        self.api_key = str(settings["api_key"])
        self.account = str(settings.get("account") or "")
        self.user = str(settings.get("user") or "")
        self.timeout = float(settings.get("timeout") or 120)
        self.wait = bool(settings.get("wait", True))

    # ------------------------------------------------------------------ HTTP
    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if self.account:
            headers["X-OpenViking-Account"] = self.account
        if self.user:
            headers["X-OpenViking-User"] = self.user
        return headers

    def _send(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        uri: str = "",
    ) -> Tuple[bytes, int]:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                http_status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            raise _parse_error(raw, exc.code, uri=uri) from exc
        except urllib.error.URLError as exc:
            raise OVRemoteError("connection", f"无法连接 OpenViking ({self.base_url}): {exc.reason}", uri=uri) from exc
        except OSError as exc:
            raise OVRemoteError("connection", f"OpenViking 传输错误: {exc}", uri=uri) from exc
        return raw, http_status

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        uri: str = "",
    ) -> Any:
        raw, http_status = self._send(method, path, query=query, body=body, uri=uri)
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            raise OVRemoteError("bad_response", "OpenViking 返回非 JSON", uri=uri, http_status=http_status) from None
        if isinstance(payload, dict) and payload.get("status") != "ok":
            err = payload.get("error") or {}
            code = str(err.get("code") or "ERROR")
            message = str(err.get("message") or payload.get("message") or "unknown error")
            raise OVRemoteError(code, message, uri=uri, details=err.get("details"), http_status=http_status)
        if isinstance(payload, dict):
            return payload.get("result")
        return payload

    # ------------------------------------------------------------- fs / 内容
    def stat(self, uri: str) -> Optional[Dict[str, Any]]:
        text = validate_uri(uri)
        try:
            return self.request("GET", "/api/v1/fs/stat", query={"uri": text}, uri=text)
        except OVRemoteError as exc:
            if exc.code == "NOT_FOUND":
                return None
            raise

    def mkdir(self, uri: str) -> Dict[str, Any]:
        text = validate_uri(uri)
        return self.request("POST", "/api/v1/fs/mkdir", body={"uri": text}, uri=text)

    def write_file(self, uri: str, content: str) -> Dict[str, Any]:
        """按目标是否存在选择 replace / create，并等待语义与向量处理。"""
        text = validate_uri(uri)
        stat = self.stat(text)
        if stat is not None and stat.get("isDir"):
            raise OVRemoteError("not_a_file", f"目标已存在且是目录: {text}", uri=text)
        mode = "replace" if stat is not None else "create"
        body: Dict[str, Any] = {
            "uri": text,
            "content": content,
            "mode": mode,
            "wait": self.wait,
        }
        return self.request("POST", "/api/v1/content/write", body=body, uri=text)

    def read(self, uri: str) -> str:
        text = validate_uri(uri)
        result = self.request("GET", "/api/v1/content/read", query={"uri": text}, uri=text)
        if result is None:
            raise OVRemoteError("read_empty", f"远端回读为空: {text}", uri=text)
        return str(result)

    def download_raw(self, uri: str) -> bytes:
        """字节级回读（content/download），用于逐字校验，不受换行规范化影响。"""
        text = validate_uri(uri)
        raw, _ = self._send("GET", "/api/v1/content/download", query={"uri": text}, uri=text)
        if not raw:
            raise OVRemoteError("read_empty", f"远端字节回读为空: {text}", uri=text)
        return raw


def check_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """连通性/鉴权自检：``/health`` + ``/ready``（只读，不写任何内容）。

    两个坑都是实测踩出来的：

    * ``/health`` 是**扁平**返回（``{"status":"ok","healthy":true,"version":...}``），
      没有 ``result`` 信封。走 ``request()`` 会被解包成 ``None``，于是自检报 ok 却什么都看不到
      （2026-10-11 对线上实例 <openviking-host>:1933 实测）。
    * ``/ready`` 才是真正说明"就绪没就绪"的探针：embedding 不可用时它会给 503，
      而 ``/health`` 照旧 200。只看 /health 会把"模型端点挂着"当成一切正常。
    """
    try:
        settings = resolve_settings(config)
    except OVConfigError as exc:
        return {"ok": False, "configured": False, "reason": str(exc), "code": "ov_config"}
    client = RemoteClient(settings)
    try:
        raw, status = client._send("GET", "/health")
    except OVRemoteError as exc:
        return {
            "ok": False,
            "configured": True,
            "server": str(settings["url"]),
            "reason": str(exc),
            "code": exc.code,
            "detail": exc.to_dict(),
        }
    result: Dict[str, Any] = {
        "ok": True,
        "configured": True,
        "server": str(settings["url"]),
        "health": _json_or_text(raw),
        "health_http": status,
    }
    try:
        ready_raw, ready_status = client._send("GET", "/ready")
        result["ready"] = _json_or_text(ready_raw)
        result["ready_http"] = ready_status
        result["ready_ok"] = ready_status < 400
    except OVRemoteError as exc:
        result["ready"] = exc.to_dict()
        result["ready_http"] = exc.http_status
        result["ready_ok"] = False
    return result


def _json_or_text(raw: bytes) -> Any:
    """能解析成 JSON 就解析，否则给一段文本（自检输出要能看懂，不是一堆字节）。"""
    text = (raw or b"").decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except Exception:
        return text[:300]


def push_files(
    config: Dict[str, Any],
    files: List[Tuple[str, str]],
    *,
    verify_read_back: bool = True,
) -> Dict[str, Any]:
    """批量推送 ``(uri, content)`` 到远端 OpenViking，逐条回读校验。

    流程：解析配置 → 逐级确保父目录存在 → 写入（create/replace，wait 处理）
    → ``content/read`` 回读逐字比对。任一文件失败都不返回成功。
    """
    try:
        settings = resolve_settings(config)
    except OVConfigError as exc:
        return {"ok": False, "configured": False, "reason": str(exc), "code": "ov_config"}
    client = RemoteClient(settings)
    if not files:
        return {"ok": True, "configured": True, "server": settings["url"], "pushed": [], "verified": 0, "failed": []}

    # 1. 收集全部父目录并按深度排序（scope 根先建，防止父目录链缺环）
    parents: Dict[str, None] = {}
    for uri, _ in files:
        for parent in parent_dirs(uri):
            parents.setdefault(parent, None)
    ordered_parents = sorted(parents, key=lambda p: p.count("/"))

    # 2. 建目录（已存在则跳过；并发竞态下的 ALREADY_EXISTS 视为成功）
    mkdir_errors: List[Dict[str, Any]] = []
    for parent in ordered_parents:
        try:
            if client.stat(parent) is None:
                client.mkdir(parent)
        except OVRemoteError as exc:
            if exc.code in ("ALREADY_EXISTS", "NOT_A_DIRECTORY"):
                continue
            mkdir_errors.append({"uri": parent, "code": exc.code, "message": str(exc)})
            break
    if mkdir_errors:
        err = mkdir_errors[0]
        return {
            "ok": False,
            "configured": True,
            "server": settings["url"],
            "code": err["code"],
            "reason": f"创建远端目录失败 {err['uri']}: {err['message']}",
            "pushed": [],
            "verified": 0,
            "failed": mkdir_errors,
        }

    # 3. 逐文件写入 + 回读校验
    pushed: List[str] = []
    failed: List[Dict[str, Any]] = []
    for uri, content in files:
        try:
            client.write_file(uri, content)
            if verify_read_back:
                try:
                    actual = client.download_raw(uri).decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise OVRemoteError(
                        "verify_not_utf8",
                        f"远端字节非 UTF-8 文本，无法按文本校验: {uri}",
                        uri=uri,
                    ) from exc
                if actual != content:
                    raise OVRemoteError(
                        "verify_mismatch",
                        f"回读内容与本地不一致（本地 {len(content)} 字节 vs 远端 {len(actual)} 字节）",
                        uri=uri,
                    )
            pushed.append(uri)
        except OVRemoteError as exc:
            failed.append({"uri": uri, "code": exc.code, "message": str(exc)})
            break

    ok = not failed
    first = failed[0] if failed else None
    return {
        "ok": ok,
        "configured": True,
        "server": settings["url"],
        "code": first["code"] if first else None,
        "reason": f"远端同步失败 {first['uri']}: {first['message']}" if first else "",
        "pushed": pushed,
        "verified": len(pushed) if verify_read_back else len(pushed),
        "failed": failed,
    }
