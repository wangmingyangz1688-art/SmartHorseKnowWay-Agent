# 2026-06-06: 一键启动后端脚本，只负责启动服务；依赖安装交给 setup.ps1，避免日常启动重复下载依赖。
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Venv = Join-Path $Backend ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Pip = Join-Path $Venv "Scripts\pip.exe"

Write-Host "[SmartHorse] Backend root: $Backend"

if (!(Test-Path (Join-Path $Backend ".env"))) {
  Write-Host "[SmartHorse] backend/.env missing. Run .\setup.ps1 first, then fill API keys."
  exit 1
}

if (!(Test-Path $Python)) {
  Write-Host "[SmartHorse] backend/.venv missing. Run .\setup.ps1 first."
  exit 1
}

Write-Host "[SmartHorse] Starting backend"
Push-Location $Backend
try {
  & $Python "run.py"
}
finally {
  Pop-Location
}
