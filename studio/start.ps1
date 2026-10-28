param(
    [switch]$Lan
)

$ErrorActionPreference = "Stop"

$studio = $PSScriptRoot
$root = Split-Path -Parent $studio
$python = Join-Path $root ".venv\Scripts\python.exe"
$index = Join-Path $studio "frontend\dist\index.html"

if (-not (Test-Path $python)) {
    throw "缺少 Python 虚拟环境：$python。请先在仓库根目录创建 .venv 并安装 studio\requirements.txt。"
}
if (-not (Test-Path $index)) {
    throw "缺少前端构建：$index。请先运行 cd studio\frontend; npm run build。"
}

$existing = Get-NetTCPConnection -LocalPort 8600 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    throw "8600 端口已被占用。请先停止占用该端口的进程，再运行本脚本。"
}

$bind = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }

Set-Location $root
Write-Host "Lunar Studio: http://127.0.0.1:8600"
if ($Lan) {
    Write-Host ""
    Write-Host "局域网地址（同一个 Wi-Fi 下的手机/电脑可以访问）："
    Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.IPAddress -notlike "192.168.245.*" -and
            $_.IPAddress -notlike "192.168.142.*"
        } |
        ForEach-Object { Write-Host ("  http://{0}:8600" -f $_.IPAddress) }
    Write-Host ""
    Write-Host "第一次从别的设备访问时，Windows 会弹防火墙提示：选“允许访问（专用网络）”。"
    Write-Host "要让外网访问，运行 studio\share.ps1。"
    Write-Host ""
}

& $python -m uvicorn studio.api.main:app --host $bind --port 8600
