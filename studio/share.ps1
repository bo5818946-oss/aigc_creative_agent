param(
    [int]$Port = 8600,
    [string]$Password = ""
)

# 让外网访问本机 Lunar Studio：
#   powershell -ExecutionPolicy Bypass -File studio\share.ps1
# 它会：生成访问密码 -> 以带密码的方式启动 API -> 起一条 Cloudflare 隧道 ->
# 打印一个 https://xxx.trycloudflare.com 地址。把地址和密码一起发给别人即可。
# 关掉：关掉窗口，或 Get-Process cloudflared | Stop-Process。

$ErrorActionPreference = "Stop"

$studio = $PSScriptRoot
$root = Split-Path -Parent $studio
$python = Join-Path $root ".venv\Scripts\python.exe"
$cloudflared = Join-Path $studio "bin\cloudflared.exe"
$index = Join-Path $studio "frontend\dist\index.html"

if (-not (Test-Path $python)) { throw "缺少 Python 虚拟环境：$python" }
if (-not (Test-Path $index)) { throw "缺少前端构建，先运行：cd studio\frontend; npm run build" }
if (-not (Test-Path $cloudflared)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $cloudflared) | Out-Null
    Write-Host "下载 cloudflared（约 55 MB，只会做一次）..."
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
        -OutFile $cloudflared -TimeoutSec 300 -UseBasicParsing
}

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    throw "端口 $Port 已被占用。先停掉已在运行的那个 API（它多半没设密码），再运行本脚本。"
}

if (-not $Password) {
    $alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    $Password = -join (1..14 | ForEach-Object { $alphabet[(Get-Random -Maximum $alphabet.Length)] })
}

$env:STUDIO_PASSWORD = $Password
$env:STUDIO_USER = "lunar"

New-Item -ItemType Directory -Force -Path (Join-Path $studio "data") | Out-Null
$apiLog = Join-Path $studio "data\share-api.log"
$apiErr = Join-Path $studio "data\share-api.err.log"

Write-Host "启动带密码的 API（端口 $Port）..."
$api = Start-Process -FilePath $python `
    -ArgumentList "-m", "uvicorn", "studio.api.main:app", "--host", "0.0.0.0", "--port", $Port `
    -WorkingDirectory $root `
    -RedirectStandardOutput $apiLog -RedirectStandardError $apiErr `
    -WindowStyle Hidden -PassThru

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $probe = New-Object System.Net.Sockets.TcpClient
        $probe.Connect("127.0.0.1", $Port)
        $probe.Close()
        Start-Sleep -Milliseconds 400
        $ready = $true
        break
    } catch { }
    if ($api.HasExited) { break }
}
if (-not $ready) {
    if (-not $api.HasExited) { Stop-Process -Id $api.Id -Force }
    throw "API 启动失败，看 $apiErr"
}

$tunnelLog = Join-Path $studio "data\share-tunnel.log"
if (Test-Path $tunnelLog) { Remove-Item $tunnelLog -Force }
Write-Host "建立 Cloudflare 隧道..."
$tunnel = Start-Process -FilePath $cloudflared `
    -ArgumentList "tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate" `
    -RedirectStandardOutput "$tunnelLog.out" -RedirectStandardError $tunnelLog `
    -WindowStyle Hidden -PassThru

$url = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $tunnelLog) {
        $match = Select-String -Path $tunnelLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($match) { $url = $match.Matches[0].Value; break }
    }
    if ($tunnel.HasExited) { throw "cloudflared 退出，看 $tunnelLog" }
}

if (-not $url) {
    throw "没有拿到公网地址，看 $tunnelLog"
}

Write-Host ""
Write-Host "==============================================="
Write-Host " 公网地址： $url"
Write-Host " 用户名：   lunar"
Write-Host " 密码：     $Password"
Write-Host "==============================================="
Write-Host ""
Write-Host "把地址 + 用户名 + 密码发给对方即可（浏览器会弹登录框）。"
Write-Host "生成仍然在这台机器的显卡上跑，所以：电脑不能休眠，ComfyUI 要开着。"
Write-Host "停止：Get-Process cloudflared | Stop-Process  然后关掉 API（进程 $($api.Id)）。"
Write-Host "注意：这个临时域名每次重启都会变。"
