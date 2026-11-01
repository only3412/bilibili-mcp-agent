from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .auth import AuthError, CredentialStore, capture_browser


def main():
    parser = argparse.ArgumentParser(description="Bilibili MCP Agent server")
    parser.add_argument("--auth-file")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--port", type=int, default=17891)
    parser.add_argument("--enable-writes", action="store_true")
    commands = parser.add_subparsers(dest="command")
    auth = commands.add_parser("auth").add_subparsers(dest="auth_command", required=True)
    auth.add_parser("status")
    auth.add_parser("init")
    capture = auth.add_parser("capture")
    capture.add_argument("--browser", choices=["edge", "chrome"], default="edge")
    capture.add_argument("--profile", default="Default")
    importer = auth.add_parser("import")
    importer.add_argument("file", type=Path)
    pair = auth.add_parser("pair")
    pair.add_argument("--timeout", type=int, default=900)
    commands.add_parser("catalog")
    args = parser.parse_args()
    store = CredentialStore(args.auth_file)
    try:
        if args.command == "auth":
            if args.auth_command == "init":
                store.initialize()
                result = store.status()
            elif args.auth_command == "status":
                result = store.status()
            elif args.auth_command == "capture":
                result = capture_browser(store, args.browser, args.profile)
            elif args.auth_command == "import":
                result = store.import_cookies(json.loads(args.file.read_text(encoding="utf-8-sig")), source="local_file")
            else:
                from .pairing import pair
                return pair(store, max(60, min(args.timeout, 1800)))
            print(json.dumps(result, ensure_ascii=True, indent=2))
        elif args.command == "catalog":
            from .catalog import catalog
            print(json.dumps(catalog(), ensure_ascii=True, indent=2))
        else:
            from .server import run
            asyncio.run(run(store, args.transport, args.port, args.enable_writes))
    except (AuthError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
