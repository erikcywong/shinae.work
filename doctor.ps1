# Feishu doctor, runnable from anywhere.
#   pwsh -File doctor.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
$env:PYTHONIOENCODING = "utf-8"
python tools/feishu_doctor.py
exit $LASTEXITCODE
