# 2026-06-06: 一键分别打开两个 PowerShell 窗口启动前后端，便于比赛 Demo。终端输出使用 ASCII，避免 Windows PowerShell 编码导致脚本解析失败。
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendScript = Join-Path $Root "start_backend.ps1"
$FrontendScript = Join-Path $Root "start_frontend.ps1"

Write-Host "[SmartHorse] Starting backend and frontend in separate PowerShell windows..."
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$BackendScript`""
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$FrontendScript`""

Write-Host "[SmartHorse] Backend: http://127.0.0.1:8000"
Write-Host "[SmartHorse] Frontend: http://127.0.0.1:8888"
