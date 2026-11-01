from __future__ import annotations

import ctypes
import hashlib
import json
import os
import secrets
import sqlite3
import tempfile
import time
from base64 import b64decode
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

COOKIE_NAMES = frozenset({"SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "buvid3", "buvid4", "buvid_fp", "b_nut", "_uuid", "sid"})
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"


class AuthError(RuntimeError):
    pass


def private_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "BilibiliMCP"


def write_private_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
        temporary = Path(file.name)
    if os.name != "nt":
        temporary.chmod(0o600)
    os.replace(temporary, path)


def iso_utc(timestamp: float | None = None) -> str:
    return datetime.fromtimestamp(timestamp or time.time(), timezone.utc).isoformat()


class CredentialStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.environ.get("BILIBILI_MCP_AUTH_FILE") or private_dir() / "credentials.local.json")

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (ValueError, OSError) as exc:
            raise AuthError("本地鉴权配置不可读；请检查文件格式及权限。") from exc

    def initialize(self) -> dict:
        data = self.load()
        if not data:
            data = {"schema_version": 1, "provider": "bilibili_web_session", "api_key": "bili_mcp_" + secrets.token_urlsafe(32), "session": None, "created_at": iso_utc()}
            write_private_json(self.path, data)
        return data

    def key(self) -> str:
        return self.initialize()["api_key"]

    def status(self) -> dict:
        data = self.load()
        session = data.get("session") or {}
        expiration = session.get("expires_at")
        return {"configured": bool(session.get("cookies")), "key_created": bool(data.get("api_key")),
                "key_file": str(self.path), "provider": "bilibili_web_session", "local_key_only": True,
                "account": session.get("account"), "expires_at": iso_utc(expiration) if expiration else None,
                "expired": bool(expiration and expiration <= time.time()),
                "source": session.get("source"), "last_verified_at": session.get("last_verified_at"),
                "cookie_names": sorted({cookie["name"] for cookie in session.get("cookies", [])})}

    def cookies(self) -> list[dict]:
        session = self.load().get("session") or {}
        expiration = session.get("expires_at")
        if expiration and expiration <= time.time():
            raise AuthError("B站会话已过期；请重新导入当前登录态。")
        return session.get("cookies", [])

    def mid(self) -> int:
        session = self.load().get("session") or {}
        mid = (session.get("account") or {}).get("mid")
        if not mid:
            raise AuthError("此工具需要B站登录态；当前尚未绑定会话。")
        return int(mid)

    def csrf(self) -> str:
        value = next((c["value"] for c in self.cookies() if c["name"] == "bili_jct"), None)
        if not value:
            raise AuthError("此操作缺少bili_jct；请重新导入完整B站会话。")
        return value

    def import_cookies(self, raw: list | dict, source: str = "browser_export") -> dict:
        rows = raw.get("cookies", []) if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            raise AuthError("会话文件必须包含cookies数组。")
        cookies = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            domain = str(row.get("domain", ".bilibili.com")).lower()
            host = domain.lstrip(".")
            if host != "bilibili.com" and not host.endswith(".bilibili.com"):
                continue
            name = row.get("name")
            value = row.get("value")
            expiration = row.get("expirationDate", row.get("expires", 0)) or 0
            if name not in COOKIE_NAMES or not isinstance(value, str) or not value or "\r" in value or "\n" in value:
                continue
            if expiration > 0 and expiration <= time.time():
                continue
            cookies.append({"name": name, "value": value, "domain": domain, "path": row.get("path", "/"), "secure": bool(row.get("secure", True)), "expires": expiration})
        if not any(c["name"] == "SESSDATA" for c in cookies):
            raise AuthError("当前导出中没有有效SESSDATA；请在已登录B站的浏览器配置中导入。")
        jar = httpx.Cookies()
        for cookie in cookies:
            jar.set(cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"])
        try:
            with httpx.Client(headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"}, cookies=jar, follow_redirects=False, timeout=20) as client:
                response = client.get("https://api.bilibili.com/x/web-interface/nav")
                response.raise_for_status()
                verified = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AuthError("B站登录校验失败，未替换已有会话。") from exc
        account = verified.get("data", {})
        if verified.get("code") != 0 or not account.get("isLogin"):
            raise AuthError(f"B站未接受该会话（code={verified.get('code')}），未替换已有会话。")
        expiration = next((c["expires"] for c in cookies if c["name"] == "SESSDATA" and c["expires"] > 0), None)
        data = self.initialize()
        data["session"] = {"source": source, "cookies": cookies, "expires_at": expiration,
                           "account": {"mid": account.get("mid"), "name": account.get("uname")},
                           "last_verified_at": iso_utc()}
        write_private_json(self.path, data)
        return self.status()


def _unprotect(blob: bytes) -> bytes:
    if os.name != "nt":
        raise AuthError("此浏览器凭证格式需要在原Windows用户下读取。")
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]
    buffer = ctypes.create_string_buffer(blob)
    source = Blob(len(blob), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    result = Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)):
        raise AuthError("Windows用户凭证解密失败。")
    try:
        return ctypes.string_at(result.data, result.length)
    finally:
        ctypes.windll.kernel32.LocalFree(result.data)


def capture_browser(store: CredentialStore, browser: str, profile: str = "Default") -> dict:
    if not profile or Path(profile).name != profile or profile in (".", ".."):
        raise AuthError("profile必须是浏览器配置目录名。")
    base = Path(os.environ["LOCALAPPDATA"]) / {"edge": "Microsoft/Edge/User Data", "chrome": "Google/Chrome/User Data"}[browser]
    path = base / profile / "Network/Cookies"
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as con:
            version = int(con.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
            rows = con.execute("SELECT host_key,name,value,encrypted_value,path,is_secure,expires_utc FROM cookies WHERE host_key='.bilibili.com' OR host_key='bilibili.com' OR host_key LIKE '%.bilibili.com'").fetchall()
    except sqlite3.Error as exc:
        raise AuthError(f"{browser}/{profile}的Cookie数据库不可读或被占用；请使用附带浏览器导入扩展。") from exc
    auth_rows = [row for row in rows if row[1] == "SESSDATA"]
    if not auth_rows:
        raise AuthError(f"{browser}/{profile}中没有B站登录凭证SESSDATA。")
    if any(bytes(row[3]).startswith(b"v20") and not row[2] for row in auth_rows):
        raise AuthError("浏览器使用应用绑定Cookie加密；请从原浏览器的cookies接口导入。")
    state = json.loads((base / "Local State").read_text(encoding="utf-8"))
    encrypted_key = b64decode(state["os_crypt"]["encrypted_key"])
    key = _unprotect(encrypted_key[5:]) if encrypted_key.startswith(b"DPAPI") else _unprotect(encrypted_key)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    cookies = []
    for host, name, value, encrypted, cookie_path, secure, expires in rows:
        if name not in COOKIE_NAMES:
            continue
        if not value:
            encrypted = bytes(encrypted)
            if encrypted.startswith(b"v20"):
                continue
            try:
                if encrypted[:3] in (b"v10", b"v11"):
                    plain = AESGCM(key).decrypt(encrypted[3:15], encrypted[15:], None)
                    if version >= 24:
                        if plain[:32] != hashlib.sha256(host.encode()).digest():
                            continue
                        plain = plain[32:]
                else:
                    plain = _unprotect(encrypted)
                value = plain.decode("utf-8")
            except Exception:
                continue
        cookies.append({"name": name, "value": value, "domain": host, "path": cookie_path, "secure": bool(secure),
                        "expires": (expires / 1_000_000 - 11644473600) if expires else 0})
    return store.import_cookies(cookies, source=f"{browser}/{profile}")
