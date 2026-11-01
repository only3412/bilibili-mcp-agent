# Bilibili MCP capabilities

The server exposes 40 site tools across 11 categories, plus the capability and auth-status tools.

| Category | Site tools |
|---|---:|
| 专栏 | 1 |
| 互动写入 | 7 |
| 动态 | 3 |
| 发现 | 5 |
| 字幕与弹幕 | 3 |
| 收藏 | 2 |
| 用户 | 4 |
| 直播 | 4 |
| 视频 | 6 |
| 评论 | 2 |
| 账号 | 3 |

The complete input schemas, authentication notes, endpoint paths, and write/read flags are in [`capabilities.json`](capabilities.json).

Write tools are disabled by default and require both `--enable-writes` and per-call `confirm: true`.
