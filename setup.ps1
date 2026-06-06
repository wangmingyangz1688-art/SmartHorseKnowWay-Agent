# 2026-06-06: Windows 首次配置脚本，复制环境模板、创建后端虚拟环境并安装前后端依赖。终端输出使用 ASCII，避免 PowerShell 编码导致脚本解析失败。
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Venv = Join-Path $Backend ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Pip = Join-Path $Venv "Scripts\pip.exe"

Write-Host "[SmartHorse] Project root: $Root"

if (!(Test-Path (Join-Path $Backend ".env"))) {
  Copy-Item (Join-Path $Backend ".env.example") (Join-Path $Backend ".env")
  Write-Host "[SmartHorse] Created backend/.env. Please fill LLM, AMap, and Neo4j settings."
}
else {
  Write-Host "[SmartHorse] backend/.env already exists. Skip copy."
}

if (!(Test-Path (Join-Path $Frontend ".env"))) {
  Copy-Item (Join-Path $Frontend ".env.example") (Join-Path $Frontend ".env")
  Write-Host "[SmartHorse] Created frontend/.env. Please fill AMap Web JS key."
}
else {
  Write-Host "[SmartHorse] frontend/.env already exists. Skip copy."
}

if (!(Test-Path $Python)) {
  Write-Host "[SmartHorse] Creating Python virtual environment..."
  py -3 -m venv $Venv
}

Write-Host "[SmartHorse] Installing/updating backend dependencies..."
& $Pip install -r (Join-Path $Backend "requirements.txt")

Write-Host "[SmartHorse] Installing/updating frontend dependencies..."
Push-Location $Frontend
try {
  npm install
}
finally {
  Pop-Location
}

Write-Host ""
Write-Host "[SmartHorse] Setup finished. Next steps:"
Write-Host "  1. Edit backend/.env: fill LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_ID, AMAP_API_KEY."
Write-Host "  2. Edit frontend/.env: fill VITE_AMAP_WEB_JS_KEY."
Write-Host "  3. Optional Neo4j: start Neo4j Desktop and set NEO4J_ENABLED=true in backend/.env."
Write-Host "  4. Run .\start_all.ps1 to start local services."
