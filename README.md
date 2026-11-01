# Bilibili MCP Agent

一个可安装到本地 Agent 宿主的 Bilibili Model Context Protocol（MCP）服务器。它把 Bilibili 的搜索、视频、字幕、弹幕、评论、用户、账号、收藏、动态、专栏和直播能力整理成结构化工具，并提供显式确认的互动写入工具。

This repository is a portable local plugin package. It contains no account
cookies, session tokens, gateway keys, browser profiles, build artifacts, or
machine-specific paths.

## Included capabilities

- 42 MCP tools across 11 categories.
- Public discovery: search, hot searches, popular videos, rankings, regions.
- Video data: details, pages, statistics, related videos, tags, play URLs.
- Subtitles and danmaku: subtitle tracks, subtitle text, XML danmaku.
- Comments and users: comment pages, replies, public profiles, uploads, relations.
- Personal reads: current account, history, watch later, favorites, feed.
- Articles and live rooms: article metadata, areas, rooms, room status, play URLs.
- Seven write tools, disabled by default and protected by per-call confirmation.
- Chromium browser-cookie import through a one-time loopback pairing flow.

The complete machine-readable catalog is in [`capabilities.json`](capabilities.json).

## Requirements

- Python 3.12 or newer.
- [`uv`](https://docs.astral.sh/uv/) on `PATH`.
- A Chromium-based browser is only needed for the optional cookie import flow.

## Run as an Agent plugin

The root [`plugin.json`](plugin.json) and [`mcp.json`](mcp.json) are the Agent
Plugins 1.0 manifests. Import the repository or package into a local plugin
host that supports stdio MCP servers. The configured command is portable:

```text
uv run --project ${PLUGIN_ROOT} bilibili-mcp
```

The first launch lets `uv` resolve the dependencies from `pyproject.toml`.
For a repeatable local environment, run the install helper first.

## Install locally

Windows PowerShell:

```powershell
.\scripts\install.ps1
```

macOS/Linux:

```bash
./scripts/install.sh
```

The helpers create a repository-local virtual environment and install the
editable package. The environment is ignored by Git.

## Import a Bilibili session

The server can use public endpoints without login. For account-scoped tools,
start the one-time browser pairing flow:

```powershell
.\scripts\login-import.ps1
```

Then load the generated unpacked extension from the private directory shown by
the command, open Bilibili in the same browser profile, and click **Import**.
The extension sends cookies only to the local pairing port. The server calls
Bilibili's `nav` endpoint to verify the session before replacing the previous
private session file.

The private store defaults to:

```text
Windows: %LOCALAPPDATA%\BilibiliMCP\credentials.local.json
Unix:    ~/.local/share/BilibiliMCP/credentials.local.json
```

Override it with `BILIBILI_MCP_AUTH_FILE`. The generated `api_key` is only a
local gateway key for the optional loopback HTTP transport; it is not a
Bilibili API key and is never included in this repository.

Check status without printing cookie or key values:

```bash
uv run --project . bilibili-mcp auth status
```

## Start the server manually

stdio (the default Agent transport):

```bash
uv run --project . bilibili-mcp
```

Loopback Streamable HTTP:

```powershell
.\scripts\run.ps1 -Http
```

The HTTP endpoint is `http://127.0.0.1:17891/mcp` and requires the generated
local Bearer key. It is deliberately bound to loopback and is not a public
remote MCP endpoint.

Enable the seven write tools only when needed:

```powershell
.\scripts\run.ps1 -EnableWrites
```

Each write call still requires `confirm: true` and a valid `bili_jct` in the
private session. The repository does not ship or request a credential.

## Development and verification

```bash
uv pip install --system --requirement requirements-lock.txt --editable .
python -m unittest discover -s tests -v
python -m compileall src
python scripts/export-capabilities.py
python -m build
```

The test suite uses local doubles and does not send Bilibili write requests.

## Scope and attribution

This is an independent client-side MCP adapter. Bilibili names and endpoints
belong to their respective owners. Use it only where your account and the
service allow the requested operation, and follow the platform's current
terms and rate limits.

## License

MIT. See [`LICENSE`](LICENSE).
