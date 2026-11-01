$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts\python.exe'

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv is required. Install it from https://docs.astral.sh/uv/ and rerun this script.'
}

if (-not (Test-Path -LiteralPath $python)) {
    & uv venv --python 3.12 $venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the virtual environment.' }
}

& uv pip install --python $python --requirement (Join-Path $root 'requirements-lock.txt') --editable $root
if ($LASTEXITCODE -ne 0) { throw 'Failed to install the locked dependencies.' }

& uv pip check --python $python
if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed.' }

Write-Host "Installed bilibili-mcp-agent into $venv"
