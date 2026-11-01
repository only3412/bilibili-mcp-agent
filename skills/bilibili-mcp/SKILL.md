---
name: bilibili-mcp
description: Use when an agent needs structured Bilibili search, video metadata, subtitles, danmaku, comments, user pages, favorites, dynamics, articles, live-room data, or explicitly confirmed account actions through the bundled local MCP server.
---

# Bilibili MCP

Use the `bilibili` MCP server for structured Bilibili operations. Prefer the
smallest read-only tool that answers the request, pass pagination cursors back
to the next call, and preserve the returned Bilibili IDs (`bvid`, `aid`, `cid`,
`mid`, `room_id`, `media_id`, and `rpid`).

The server exposes 42 tools in 11 categories. Call `bilibili_capabilities` when
the required endpoint or input schema is unclear. Public tools can run without
a session; account-scoped tools require a locally imported Bilibili session.

Write tools are disabled unless the process is started with
`--enable-writes`. Every write call also requires `confirm: true`; do not add
that flag unless the user has clearly requested the specific state change.

Authentication is local to the user's machine. The server stores a generated
loopback key and imported Bilibili cookies outside the repository. Never copy
those values into prompts, logs, source files, issues, or commits.
