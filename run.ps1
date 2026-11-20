# Coffee Super-Agent OS — one-command runner
param(
  [int]$Port = 8787,
  [switch]$Live,
  [string]$VarDir = "",
  [switch]$Reset
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
$env:PYTHONIOENCODING = "utf-8"

if ($Reset -and (Test-Path "var")) {
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $backup = "var\backups\state-$stamp.db"
  New-Item -ItemType Directory -Force -Path "var\backups" | Out-Null
  if (Test-Path "var\state.db") {
    Copy-Item "var\state.db" $backup
    Write-Host "state backed up -> $backup" -ForegroundColor Yellow
  }
  # keep secrets (feishu.env) and tickets; drop the database only
  Get-ChildItem "var" -Force | Where-Object { $_.Name -notin @("feishu.env", "backups") } |
    Remove-Item -Recurse -Force
  Write-Host "state reset (credentials preserved)" -ForegroundColor Yellow
}

$pyArgs = @("app/server.py", "--port", "$Port")
if ($Live)   { $pyArgs += "--live" }
if ($VarDir) { $pyArgs += @("--var", $VarDir) }

Write-Host "Coffee Super-Agent OS -> http://127.0.0.1:$Port" -ForegroundColor Green
python @pyArgs
