from __future__ import annotations

import asyncio
import hashlib
import json
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlencode, urlsplit

import httpx

from .auth import AuthError, CredentialStore, UA
from .catalog import Endpoint

MIXIN = (46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52)
API_HOSTS = frozenset({"api.bilibili.com", "api.live.bilibili.com"})


class ApiError(RuntimeError):
    def __init__(self, kind: str, message: str, code=None):
        super().__init__(message)
        self.kind, self.code = kind, code


def sign_wbi(params: dict, image_key: str, sub_key: str, timestamp: int | None = None) -> dict:
    key = image_key + sub_key
    if len(key) < 64:
        raise ApiError("wbi", "WBI密钥格式无效。")
    mixin = "".join(key[n] for n in MIXIN)[:32]
    clean = {**params, "wts": timestamp if timestamp is not None else int(time.time())}
    clean = {key: "".join(c for c in str(value) if c not in "!'()*") for key, value in sorted(clean.items())}
    clean["w_rid"] = hashlib.md5((urlencode(clean, quote_via=quote) + mixin).encode()).hexdigest()
    return clean


def subtitle_url(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if (parts.scheme != "https" or not host.endswith(".hdslb.com") or parts.username or parts.password
        or parts.port not in (None, 443) or parts.fragment or not parts.path.startswith(("/bfs/subtitle/", "/bfs/ai_subtitle/"))):
        raise ApiError("input", "仅接受B站字幕接口返回的https://*.hdslb.com/bfs/(ai_)subtitle/地址。")
    return url


class BilibiliApi:
    def __init__(self, store: CredentialStore, transport=None, interval: float = 0.4):
        self.store = store
        self.interval = interval
        self.test_transport = transport
        self.last_request = 0.0
        self.lock = asyncio.Lock()
        self.client = httpx.AsyncClient(headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"}, timeout=25,
                                        follow_redirects=False, transport=transport, limits=httpx.Limits(max_connections=2))
        self.public = httpx.AsyncClient(headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"}, timeout=25, follow_redirects=False, transport=transport)
        self.wbi: tuple[str, str] | None = None
        self.wbi_at = 0.0
        self.context_cookies: list[dict] = []
        self.context_ready = False
        self.context_lock = asyncio.Lock()

    async def site_context(self):
        if self.context_ready:
            return
        async with self.context_lock:
            if self.context_ready:
                return
            try:
                cookies = self.store.cookies()
            except AuthError:
                cookies = []
            if not any(cookie["name"] == "buvid3" for cookie in cookies):
                jar = httpx.Cookies()
                for cookie in cookies:
                    jar.set(cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"])
                # The official homepage issues normal device cookies. They stay in
                # this process and never replace the imported authentication state.
                async with httpx.AsyncClient(headers={"User-Agent": UA}, cookies=jar, timeout=20,
                                              follow_redirects=False, transport=self.test_transport) as bootstrap:
                    try:
                        response = await bootstrap.get("https://www.bilibili.com/")
                        response.raise_for_status()
                        self.context_cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
                                                for c in bootstrap.cookies.jar if c.name in ("buvid3", "buvid4", "b_nut") and c.domain.lstrip(".") == "bilibili.com"]
                    except httpx.HTTPError:
                        # These cookies are optional; the actual API result remains
                        # authoritative if the homepage is temporarily unavailable.
                        pass
            self.context_ready = True

    async def close(self):
        await self.client.aclose()
        await self.public.aclose()

    async def raw(self, host: str, path: str, params: dict, method="GET", auth=False) -> httpx.Response:
        if host not in API_HOSTS or not path.startswith("/x/") and host == "api.bilibili.com":
            raise ApiError("input", "未知API目标。")
        try:
            cookies = self.store.cookies()
        except AuthError:
            if auth:
                raise
            cookies = []
        if auth:
            self.store.mid()
            if not any(c["name"] == "SESSDATA" for c in cookies):
                raise AuthError("当前没有可用B站登录态。")
        async with self.lock:
            await asyncio.sleep(max(0, self.last_request + self.interval - time.monotonic()))
            self.client.cookies.clear()
            existing = {c["name"] for c in cookies}
            for cookie in cookies + [c for c in self.context_cookies if c["name"] not in existing]:
                self.client.cookies.set(cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"])
            headers = {}
            if path.startswith("/x/space/") and params.get("mid"):
                headers["Referer"] = f"https://space.bilibili.com/{params['mid']}/"
            elif path == "/x/polymer/web-dynamic/v1/feed/space" and params.get("host_mid"):
                headers["Referer"] = f"https://space.bilibili.com/{params['host_mid']}/dynamic"
            try:
                response = await self.client.request(method, f"https://{host}{path}", params=params if method == "GET" else None,
                                                     data=params if method == "POST" else None, headers=headers)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ApiError("http", f"B站返回HTTP {exc.response.status_code}。", exc.response.status_code) from exc
            except httpx.HTTPError as exc:
                raise ApiError("network", f"B站网络请求失败（{type(exc).__name__}）。") from exc
            finally:
                self.last_request = time.monotonic()
        return response

    async def json(self, host: str, path: str, params: dict, method="GET", auth=False, allow_anonymous_nav=False) -> dict:
        response = await self.raw(host, path, params, method, auth)
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiError("upstream", "B站响应不是JSON。") from exc
        code = data.get("code", 0)
        if code != 0 and not (allow_anonymous_nav and code == -101):
            raise ApiError("upstream_api", str(data.get("message", data.get("msg", "API调用失败")))[:300], code)
        return data

    async def wbi_parameters(self, params: dict) -> dict:
        if self.wbi is None or time.monotonic() - self.wbi_at > 600:
            result = await self.json("api.bilibili.com", "/x/web-interface/nav", {}, allow_anonymous_nav=True)
            images = result.get("data", {}).get("wbi_img", {})
            try:
                self.wbi = tuple(urlsplit(images[key]).path.rsplit("/", 1)[-1].split(".")[0] for key in ("img_url", "sub_url"))
            except (KeyError, TypeError) as exc:
                raise ApiError("wbi", "当前nav响应没有WBI密钥。") from exc
            self.wbi_at = time.monotonic()
        return sign_wbi(params, *self.wbi)

    async def call(self, endpoint: Endpoint, args: dict, enable_writes=False) -> dict:
        params = endpoint.parameters(args)
        if endpoint.method == "POST":
            if not enable_writes or params.pop("confirm", False) is not True:
                raise ApiError("write_disabled", "写操作需以--enable-writes启动服务，并传confirm=true。")
            params["csrf"] = self.store.csrf()
            params["csrf_token"] = params["csrf"]
            if endpoint.name == "bilibili_video_favorite" and not (params.get("add_media_ids") or params.get("del_media_ids")):
                raise ApiError("input", "至少指定加入或移出的收藏夹。")
        if endpoint.handler == "self_mid" and not params.get("up_mid"):
            params["up_mid"] = self.store.mid()
        if endpoint.auth:
            self.store.mid()
            self.store.cookies()
        if endpoint.handler == "subtitle":
            url = subtitle_url(params["url"])
            try:
                async with self.public.stream("GET", url) as response:
                    response.raise_for_status()
                    parts = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 4_000_000:
                            raise ApiError("size", "字幕响应超过4MB。")
                        parts.append(chunk)
                body = json.loads(b"".join(parts)).get("body", [])
            except (httpx.HTTPError, ValueError) as exc:
                raise ApiError("subtitle", "字幕获取失败；链接可能已过期。") from exc
            return {"ok": True, "data": {"segments": body, "text": "\n".join(row.get("content", "") for row in body)}}
        if endpoint.handler == "danmaku":
            limit = params.pop("limit")
            response = await self.raw(endpoint.host, endpoint.path, params)
            if len(response.content) > 10_000_000:
                raise ApiError("size", "弹幕XML响应超过10MB。")
            try:
                root = ET.fromstring(response.content)
            except ET.ParseError as exc:
                raise ApiError("upstream", "弹幕接口返回的不是有效XML。") from exc
            rows = root.findall("d")
            return {"ok": True, "data": {"total": len(rows), "returned": min(len(rows), limit), "items": [{"p": row.attrib.get("p"), "text": row.text} for row in rows[:limit]]}}
        await self.site_context()
        if endpoint.name in ("bilibili_user_info", "bilibili_user_videos"):
            params["web_location"] = "333.1387"
        if endpoint.name == "bilibili_user_feed":
            params.update({"timezone_offset": -480, "platform": "web", "web_location": "333.1387"})
        if endpoint.wbi:
            params = await self.wbi_parameters(params)
        result = await self.json(endpoint.host, endpoint.path, params, endpoint.method, endpoint.auth)
        data = result.get("data", result.get("result", result))
        if isinstance(data, dict) and (data.get("v_voucher") or data.get("is_risk") is True):
            raise ApiError("risk_control", "B站返回风控占位内容，本次未取得实际资料。")
        if endpoint.handler == "video_stat":
            if not isinstance(data, dict) or not isinstance(data.get("stat"), dict):
                raise ApiError("upstream", "视频详情响应缺少统计字段。")
            data = data["stat"]
        return {"ok": True, "code": 0, "data": data, "endpoint": endpoint.path}

    def redact(self, text: str) -> str:
        config = self.store.load()
        secrets = [config.get("api_key", "")] + [cookie.get("value", "") for cookie in (config.get("session") or {}).get("cookies", [])]
        for secret in secrets:
            if len(secret) >= 8:
                text = text.replace(secret, "[REDACTED]")
        return text
