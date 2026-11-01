from __future__ import annotations

import hmac
import json
import secrets
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .auth import AuthError, CredentialStore, private_dir, write_private_json


def pair(store: CredentialStore, timeout: int = 600) -> None:
    token = secrets.token_urlsafe(32)
    extension = private_dir() / "browser-import"
    source = Path(__file__).resolve().parent / "browser_import"
    if not source.exists():
        source = Path(__file__).resolve().parents[2] / "browser-import"
    shutil.copytree(source, extension, dirs_exist_ok=True)
    write_private_json(extension / "pairing.local.json", {"token": token, "expires_at": time.time() + timeout})
    deadline = time.monotonic() + timeout
    used = False

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def origin(self) -> str | None:
            origin = self.headers.get("Origin", "")
            if origin.startswith("chrome-extension://") or origin.startswith("moz-extension://"):
                return origin
            return None

        def reply(self, status: int, data: dict):
            raw = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            if self.origin():
                self.send_header("Access-Control-Allow-Origin", self.origin())
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self):
            if not self.origin():
                return self.reply(403, {"ok": False})
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.origin())
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Bilibili-Pair")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.end_headers()

        def do_POST(self):
            nonlocal used
            if self.path != "/session/import" or self.headers.get("Host") != "127.0.0.1:17890":
                return self.reply(404, {"ok": False})
            if used or time.monotonic() >= deadline or not hmac.compare_digest(self.headers.get("X-Bilibili-Pair", ""), token):
                return self.reply(403, {"ok": False, "error": "配对已过期或无效，请重新运行登录导入。"})
            if self.headers.get("Origin") and not self.origin():
                return self.reply(403, {"ok": False})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 262144:
                    return self.reply(413, {"ok": False})
                raw = json.loads(self.rfile.read(length))
                result = store.import_cookies(raw, source="browser_cookies_api")
            except (AuthError, ValueError) as exc:
                return self.reply(422, {"ok": False, "error": str(exc)})
            used = True
            self.reply(200, {"ok": True, "account": result["account"], "expires_at": result["expires_at"]})
            print(json.dumps({"event": "session_imported", **result}, ensure_ascii=True), flush=True)
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    with ThreadingHTTPServer(("127.0.0.1", 17890), Handler) as server:
        server.daemon_threads = True
        timer = threading.Timer(timeout, server.shutdown)
        timer.daemon = True
        timer.start()
        print(json.dumps({"event": "pairing_ready", "extension_directory": str(extension), "timeout_seconds": timeout,
                          "listen": "127.0.0.1:17890", "token_displayed": False}, ensure_ascii=True), flush=True)
        try:
            server.serve_forever(poll_interval=0.5)
        finally:
            timer.cancel()
