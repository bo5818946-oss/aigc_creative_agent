$ErrorActionPreference = "Stop"

$studio = $PSScriptRoot
$root = Split-Path -Parent $studio
$python = Join-Path $root ".venv\Scripts\python.exe"
$frontend = Join-Path $studio "frontend"

if (-not (Test-Path $python)) {
    throw "缺少 Python 虚拟环境：$python。请先在仓库根目录创建 .venv 并安装 studio\requirements.txt。"
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    throw "缺少前端依赖：$frontend\node_modules。请先运行 cd studio\frontend; npm install。"
}

$api = $null
$existing = Get-NetTCPConnection -LocalPort 8600 -State Listen -ErrorAction SilentlyContinue
if (-not $existing) {
    New-Item -ItemType Directory -Force -Path (Join-Path $studio "data") | Out-Null
    $log = Join-Path $studio "data\api-dev.log"
    $err = Join-Path $studio "data\api-dev.err.log"
    Write-Host "Starting Lumen API on http://127.0.0.1:8600 ..."
    $api = Start-Process `
        -FilePath $python `
        -ArgumentList "-m", "uvicorn", "studio.api.main:app", "--host", "127.0.0.1", "--port", "8600" `
        -WorkingDirectory $root `
        -RedirectStandardOutput $log `
        -RedirectStandardError $err `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Seconds 2
    if ($api.HasExited) {
        throw "API 启动失败，请查看 $err"
    }
} else {
    Write-Host "Port 8600 is already in use; reusing the running API."
}

try {
    Set-Location $frontend
    Write-Host "Starting Vite on http://127.0.0.1:5173 ..."
    npm run dev
} finally {
    if ($api -and -not $api.HasExited) {
        Stop-Process -Id $api.Id -Force
    }
}
