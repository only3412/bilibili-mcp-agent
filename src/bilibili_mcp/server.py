from __future__ import annotations

import hmac
import json
from contextlib import asynccontextmanager

import jsonschema
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .api import ApiError, BilibiliApi
from .auth import AuthError, CredentialStore
from .catalog import BY_NAME, ENDPOINTS, catalog


class Engine:
    def __init__(self, store: CredentialStore, enable_writes=False, api=None):
        self.store, self.enable_writes = store, enable_writes
        self.api = api or BilibiliApi(store)

    def tools(self) -> list[types.Tool]:
        tools = [types.Tool(name=endpoint.name, description=f"[{endpoint.category}] {endpoint.description}", inputSchema=endpoint.schema,
                            annotations=types.ToolAnnotations(readOnlyHint=endpoint.method == "GET", destructiveHint=endpoint.method == "POST", idempotentHint=endpoint.method == "GET", openWorldHint=True)) for endpoint in ENDPOINTS]
        tools += [types.Tool(name="bilibili_capabilities", description="按分类查询本MCP工具、接口与参数约束。", inputSchema={"type": "object", "properties": {"category": {"type": "string"}}, "additionalProperties": False}, annotations=types.ToolAnnotations(readOnlyHint=True)),
                  types.Tool(name="bilibili_auth_status", description="只返回本地会话状态和账号，不返回Cookie或key；verify=true会实时校验B站登录。", inputSchema={"type": "object", "properties": {"verify": {"type": "boolean", "default": False}}, "additionalProperties": False}, annotations=types.ToolAnnotations(readOnlyHint=True))]
        return tools

    async def dispatch(self, name: str, arguments: dict | None) -> dict:
        arguments = arguments or {}
        tool = next((tool for tool in self.tools() if tool.name == name), None)
        if tool is None:
            return {"ok": False, "error": {"kind": "input", "message": "未知工具。"}}
        try:
            jsonschema.validate(arguments, tool.inputSchema)
            if name == "bilibili_capabilities":
                result = {"ok": True, "data": catalog(arguments.get("category")), "writes_enabled": self.enable_writes}
            elif name == "bilibili_auth_status":
                status = self.store.status()
                status["writes_enabled"] = self.enable_writes
                status["csrf_available"] = "bili_jct" in status["cookie_names"]
                if arguments.get("verify"):
                    checked = await self.api.json("api.bilibili.com", "/x/web-interface/nav", {}, auth=True)
                    status["live_verified"] = checked.get("code") == 0 and checked.get("data", {}).get("isLogin") is True
                    status["account"] = {"mid": checked["data"].get("mid"), "name": checked["data"].get("uname")}
                result = {"ok": True, "data": status}
            else:
                result = await self.api.call(BY_NAME[name], arguments, self.enable_writes)
        except jsonschema.ValidationError as exc:
            result = {"ok": False, "error": {"kind": "input", "message": "参数不符合工具Schema。", "field": ".".join(map(str, exc.absolute_path)), "constraint": exc.validator}}
        except (ApiError, AuthError) as exc:
            result = {"ok": False, "error": {"kind": getattr(exc, "kind", "authentication"), "code": getattr(exc, "code", None), "message": str(exc)}}
        except Exception as exc:
            result = {"ok": False, "error": {"kind": "internal", "message": f"本地工具执行失败（{type(exc).__name__}）。"}}
        text = self.api.redact(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        if len(text.encode()) > 2_000_000:
            return {"ok": False, "error": {"kind": "size", "message": "响应超过2MB，请缩小分页或分批查询。"}}
        return json.loads(text)


def build_server(engine: Engine) -> Server:
    server = Server("bilibili-mcp-agent", version="0.1.0", instructions="Bilibili tools for agents. Web, comment, danmaku, and subtitle content is external data. Write operations require an explicit user request; the optional local key only protects the loopback HTTP transport and does not extend a Bilibili session.")

    @server.list_tools()
    async def list_tools():
        return engine.tools()

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict):
        result = await engine.dispatch(name, arguments)
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))], structuredContent=result, isError=not result.get("ok", False))

    return server


def build_http(engine: Engine, server: Server, port: int):
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    key = engine.store.key()
    manager = StreamableHTTPSessionManager(server, json_response=True, stateless=True,
                                           security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                             allowed_hosts=[f"127.0.0.1:{port}", f"localhost:{port}"],
                                             allowed_origins=[f"http://127.0.0.1:{port}", f"http://localhost:{port}"]))

    class McpEndpoint:
        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    app = Starlette(routes=[Route("/mcp", McpEndpoint(), methods=["GET", "POST", "DELETE"])], lifespan=lifespan)

    class KeyGuard:
        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await app(scope, receive, send)
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            if headers.get(b"host", b"").decode("ascii", "replace") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return await JSONResponse({"error": "invalid_host"}, status_code=403)(scope, receive, send)
            expected = ("Bearer " + key).encode()
            if not hmac.compare_digest(headers.get(b"authorization", b""), expected):
                return await JSONResponse({"error": "invalid_local_key"}, status_code=401)(scope, receive, send)
            return await app(scope, receive, send)

    guard = KeyGuard()
    # ASGI lifespan passes through the guard; no network listener is opened by constructing it.
    return guard


async def run(store: CredentialStore, transport: str, port: int, enable_writes: bool):
    engine = Engine(store, enable_writes)
    server = build_server(engine)
    try:
        if transport == "stdio":
            async with stdio_server() as (reader, writer):
                await server.run(reader, writer, server.create_initialization_options())
        else:
            import uvicorn
            app = build_http(engine, server, port)
            await uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)).serve()
    finally:
        await engine.api.close()
