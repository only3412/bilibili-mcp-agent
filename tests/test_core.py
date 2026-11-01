from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import jsonschema

from bilibili_mcp.api import ApiError, BilibiliApi, sign_wbi, subtitle_url
from bilibili_mcp.auth import AuthError, CredentialStore, write_private_json
from bilibili_mcp.catalog import BY_NAME, ENDPOINTS
from bilibili_mcp.server import Engine, build_http, build_server


class CoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bilibili-mcp-test-")
        self.store = CredentialStore(Path(self.temporary.name) / "auth.local.json")

    def tearDown(self):
        self.temporary.cleanup()

    def add_session(self, *, expiry=None, csrf=False):
        data = self.store.initialize()
        cookies = [{"name": "SESSDATA", "value": "test-session-secret-123456", "domain": ".bilibili.com", "path": "/"}]
        if csrf:
            cookies.append({"name": "bili_jct", "value": "test-csrf-secret-123456", "domain": ".bilibili.com", "path": "/"})
        data["session"] = {"cookies": cookies, "expires_at": expiry, "account": {"mid": 42, "name": "test"}}
        write_private_json(self.store.path, data)

    def test_key_stable_and_no_secret_in_status(self):
        first = self.store.key()
        self.assertEqual(first, self.store.key())
        self.assertNotIn(first, json.dumps(self.store.status()))
        self.assertTrue(first.startswith("bili_mcp_"))

    def test_expired_session_rejected(self):
        self.add_session(expiry=time.time() - 30)
        with self.assertRaises(AuthError):
            self.store.cookies()

    def test_all_tool_schemas_valid_and_names_unique(self):
        self.assertEqual(len(BY_NAME), len(ENDPOINTS))
        for endpoint in ENDPOINTS:
            jsonschema.Draft202012Validator.check_schema(endpoint.schema)

    def test_subtitle_url_restricts_destination(self):
        self.assertTrue(subtitle_url("//aisubtitle.hdslb.com/bfs/ai_subtitle/abc.json").startswith("https:"))
        for url in ("http://aisubtitle.hdslb.com/bfs/subtitle/a", "https://aisubtitle.hdslb.com.evil.example/bfs/subtitle/a", "https://127.0.0.1/bfs/subtitle/a", "https://u:p@aisubtitle.hdslb.com/bfs/subtitle/a", "https://aisubtitle.hdslb.com:8080/bfs/subtitle/a", "https://aisubtitle.hdslb.com/anything"):
            with self.subTest(url=url), self.assertRaises(ApiError):
                subtitle_url(url)

    def test_wbi_known_vector(self):
        result = sign_wbi({"foo": 114, "bar": 514, "zab": 1919810}, "7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45", 1702204169)
        self.assertEqual(result["w_rid"], "8f6f2b5b3d485fe1886cec6a0be8c5d4")
        self.assertEqual(result["wts"], "1702204169")

    def test_wbi_filters_special_characters(self):
        result = sign_wbi({"text": "a!'()*b", "z": 2}, "7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45", 1)
        self.assertEqual(result["text"], "ab")

    def test_import_rejects_foreign_cookie_without_touching_config(self):
        self.add_session()
        original = self.store.path.read_bytes()
        with self.assertRaises(AuthError):
            self.store.import_cookies([{"name": "SESSDATA", "value": "foreign-secret", "domain": ".bilibili.com.evil.test"}])
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_rejected_login_preserves_previous_session(self):
        self.add_session()
        original = self.store.path.read_bytes()
        mock_response = httpx.Response(200, json={"code": -101, "data": {"isLogin": False}}, request=httpx.Request("GET", "https://api.bilibili.com/x/web-interface/nav"))
        with patch("bilibili_mcp.auth.httpx.Client") as client:
            client.return_value.__enter__.return_value.get.return_value = mock_response
            with self.assertRaises(AuthError):
                self.store.import_cookies([{"name": "SESSDATA", "value": "bad-session-secret", "domain": ".bilibili.com"}])
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_successful_import_binds_verified_identity_and_reuses_key(self):
        key = self.store.key()
        response = httpx.Response(200, json={"code": 0, "data": {"isLogin": True, "mid": 99, "uname": "checked"}}, request=httpx.Request("GET", "https://api.bilibili.com/x/web-interface/nav"))
        with patch("bilibili_mcp.auth.httpx.Client") as client:
            client.return_value.__enter__.return_value.get.return_value = response
            result = self.store.import_cookies([{"name": "SESSDATA", "value": "new-session-secret", "domain": ".bilibili.com"}, {"name": "other", "value": "do-not-store", "domain": ".bilibili.com"}])
        self.assertEqual(result["account"]["mid"], 99)
        self.assertEqual(self.store.key(), key)
        self.assertNotIn("do-not-store", self.store.path.read_text())

    async def test_no_auth_calls_network_for_private_operation(self):
        calls = []
        api = BilibiliApi(self.store, httpx.MockTransport(lambda request: calls.append(request)), interval=0)
        engine = Engine(self.store, api=api)
        result = await engine.dispatch("bilibili_my_history", {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["kind"], "authentication")
        self.assertEqual(calls, [])
        await api.close()

    async def test_input_validation_prevents_network(self):
        calls = []
        api = BilibiliApi(self.store, httpx.MockTransport(lambda request: calls.append(request)), interval=0)
        result = await Engine(self.store, api=api).dispatch("bilibili_video_info", {"bvid": "../../bad", "extra": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(calls, [])
        await api.close()

    async def test_write_disabled_does_not_send_request(self):
        self.add_session(csrf=True)
        calls = []
        api = BilibiliApi(self.store, httpx.MockTransport(lambda request: calls.append(request)), interval=0)
        result = await Engine(self.store, api=api).dispatch("bilibili_video_like", {"aid": 1, "like": 1, "confirm": True})
        self.assertEqual(result["error"]["kind"], "write_disabled")
        self.assertEqual(calls, [])
        await api.close()

    async def test_write_requires_per_call_confirmation(self):
        self.add_session(csrf=True)
        calls = []
        api = BilibiliApi(self.store, httpx.MockTransport(lambda request: calls.append(request)), interval=0)
        result = await Engine(self.store, enable_writes=True, api=api).dispatch("bilibili_video_like", {"aid": 1, "like": 1, "confirm": False})
        self.assertEqual(result["error"]["kind"], "input")
        self.assertEqual(calls, [])
        await api.close()

    async def test_current_session_reload_cookie_scoping_and_redaction(self):
        self.add_session(csrf=True)
        seen = []
        def respond(request):
            seen.append(request.headers.get("cookie"))
            return httpx.Response(200, json={"code": 0, "data": {"echo": "test-session-secret-123456", "value": 1}})
        api = BilibiliApi(self.store, httpx.MockTransport(respond), interval=0)
        engine = Engine(self.store, api=api)
        result = await engine.dispatch("bilibili_me", {})
        self.assertEqual(result["data"]["echo"], "[REDACTED]")
        self.assertIn("SESSDATA=", seen[-1])
        data = self.store.load()
        data["session"]["cookies"][0]["value"] = "second-session-secret-654321"
        write_private_json(self.store.path, data)
        await engine.dispatch("bilibili_me", {})
        self.assertIn("second-session-secret-654321", seen[-1])
        self.assertNotIn("test-session-secret-123456", seen[-1])
        await api.close()

    async def test_upstream_error_remains_error(self):
        api = BilibiliApi(self.store, httpx.MockTransport(lambda r: httpx.Response(200, json={"code": -352, "message": "risk control"})), interval=0)
        result = await Engine(self.store, api=api).dispatch("bilibili_popular", {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], -352)
        await api.close()

    async def test_risk_placeholder_is_not_success(self):
        api = BilibiliApi(self.store, httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 0, "data": {"is_risk": True, "list": {"vlist": []}}})), interval=0)
        api.wbi = ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45")
        api.wbi_at = time.monotonic()
        result = await Engine(self.store, api=api).dispatch("bilibili_user_videos", {"mid": 1})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["kind"], "risk_control")
        await api.close()

    async def test_video_stat_extracts_current_endpoint(self):
        calls = []
        def respond(request):
            calls.append(request.url.path)
            return httpx.Response(200, json={"code": 0, "data": {"bvid": "BV1TxxC6vEo4", "stat": {"view": 100, "like": 3}}})
        api = BilibiliApi(self.store, httpx.MockTransport(respond), interval=0)
        result = await Engine(self.store, api=api).dispatch("bilibili_video_stat", {"bvid": "BV1TxxC6vEo4"})
        self.assertEqual(result["data"], {"view": 100, "like": 3})
        self.assertEqual(calls[-1], "/x/web-interface/view")
        await api.close()

    async def test_anonymous_nav_still_supplies_wbi_key(self):
        requests = []
        def respond(request):
            requests.append(request)
            if request.url.path.endswith("/nav"):
                return httpx.Response(200, json={"code": -101, "data": {"wbi_img": {"img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png", "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png"}}})
            return httpx.Response(200, json={"code": 0, "data": {"mid": 1}})
        api = BilibiliApi(self.store, httpx.MockTransport(respond), interval=0)
        result = await Engine(self.store, api=api).dispatch("bilibili_user_info", {"mid": 1})
        self.assertTrue(result["ok"])
        self.assertIn("w_rid", requests[-1].url.params)
        await api.close()

    async def test_http_requires_local_key_and_checks_host(self):
        engine = Engine(self.store)
        app = build_http(engine, build_server(engine), 17891)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:17891") as client:
            self.assertEqual((await client.post("/mcp", json={})).status_code, 401)
            self.assertEqual((await client.post("/mcp", json={}, headers={"Authorization": "Bearer wrong"})).status_code, 401)
            self.assertEqual((await client.post("/mcp", json={}, headers={"Authorization": "Bearer " + self.store.key(), "Host": "evil.example"})).status_code, 403)
        await engine.api.close()


if __name__ == "__main__":
    unittest.main()
