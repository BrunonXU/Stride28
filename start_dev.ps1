# 一键启动开发环境：FastAPI 后端 + Vite 前端
# 用法：在项目根目录运行 .\start_dev.ps1

Write-Host "启动 FastAPI 后端 (port 8000)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000" -WorkingDirectory $PSScriptRoot

Start-Sleep -Seconds 2

Write-Host "启动 Vite 前端 (port 3000)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "npm run dev" -WorkingDirectory "$PSScriptRoot\frontend"

Write-Host "两个窗口已启动，访问 http://localhost:3000" -ForegroundColor Green
