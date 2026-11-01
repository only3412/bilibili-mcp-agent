param(
    [switch]$Http,
    [switch]$EnableWrites,
    [int]$Port = 17891
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:PYTHONUTF8 = '1'
$cliArgs = @()
if ($Http) { $cliArgs += @('--transport', 'http', '--port', "$Port") }
if ($EnableWrites) { $cliArgs += '--enable-writes' }
& uv run --project $root bilibili-mcp @cliArgs
exit $LASTEXITCODE
