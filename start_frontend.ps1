# 2026-06-06: 一键启动前端脚本，只负责启动服务；依赖安装交给 setup.ps1，避免日常启动重复下载依赖。
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Frontend = Join-Path $Root "frontend"

Write-Host "[SmartHorse] Frontend root: $Frontend"

if (!(Test-Path (Join-Path $Frontend ".env"))) {
  Write-Host "[SmartHorse] frontend/.env missing. Run .\setup.ps1 first, then fill AMap Web JS key."
  exit 1
}

Push-Location $Frontend
try {
  if (!(Test-Path "node_modules")) {
    Write-Host "[SmartHorse] frontend/node_modules missing. Run .\setup.ps1 first."
    exit 1
  }
  Write-Host "[SmartHorse] Starting frontend: http://127.0.0.1:8888"
  npm run dev
}
finally {
  Pop-Location
}
