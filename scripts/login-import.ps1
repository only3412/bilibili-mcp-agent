$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:PYTHONUTF8 = '1'
& uv run --project $root bilibili-mcp auth pair --timeout 900
exit $LASTEXITCODE
