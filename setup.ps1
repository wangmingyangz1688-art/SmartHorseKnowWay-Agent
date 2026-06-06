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

# ==========================================
# Node.js Version Check for Windows (ASCII Output)
# ==========================================
Write-Host "[SmartHorse] Checking Node.js environment (requires >= 22.0)..."
$nodeOk = $false

if (Get-Command "node" -ErrorAction SilentlyContinue) {
  $nodeVersionStr = node -v
  # Extract major version number (e.g., "v22.1.0" -> 22)
  if ($nodeVersionStr -match "v(\d+)\.") {
    $nodeMajor = [int]$matches[1]
    if ($nodeMajor -ge 22) {
      $nodeOk = $true
      Write-Host "[SmartHorse] Current Node.js version is $nodeVersionStr, requirement met."
    }
  }
}

if (-not $nodeOk) {
  Write-Host "[SmartHorse] WARNING: Node.js is missing or version is below 22.0." -ForegroundColor Yellow
    
  # Try to rescue with nvm-windows if available
  if (Get-Command "nvm" -ErrorAction SilentlyContinue) {
    Write-Host "[SmartHorse] Detected nvm-windows. Attempting to install/use Node.js 22..." -ForegroundColor Cyan
    nvm install 22
    nvm use 22
  }
  else {
    Write-Host "[SmartHorse] FATAL ERROR: Qualified Node.js not found and nvm-windows is missing." -ForegroundColor Red
    Write-Host "[SmartHorse] Fix it by running this in an Administrator PowerShell:" -ForegroundColor White
    Write-Host "             winget install OpenJS.NodeJS" -ForegroundColor Green
    Write-Host "[SmartHorse] Or manually download version 22+ from https://nodejs.org/" -ForegroundColor White
    Write-Host "[SmartHorse] Restart your terminal after installation and run this script again." -ForegroundColor Yellow
    exit 1
  }
}
# ==========================================

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