from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bilibili_mcp.catalog import catalog  # noqa: E402


def main() -> None:
    data = catalog()
    (ROOT / "capabilities.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    counts: dict[str, int] = {}
    for tool in data["tools"]:
        counts[tool["category"]] = counts.get(tool["category"], 0) + 1
    lines = [
        "# Bilibili MCP capabilities",
        "",
        f"The server exposes {len(data['tools'])} site tools across {len(counts)} categories, plus the capability and auth-status tools.",
        "",
        "| Category | Site tools |",
        "|---|---:|",
    ]
    lines.extend(f"| {category} | {counts[category]} |" for category in sorted(counts))
    lines += [
        "",
        "The complete input schemas, authentication notes, endpoint paths, and write/read flags are in [`capabilities.json`](capabilities.json).",
        "",
        "Write tools are disabled by default and require both `--enable-writes` and per-call `confirm: true`.",
    ]
    (ROOT / "CAPABILITIES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
