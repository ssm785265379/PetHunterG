# 宠物猎人G —— 本地服务一键启动
#
# 这个脚本把每次开机都要手动做的四件事固化下来，顺序很重要：
#   1) 关掉遗留的服务实例（否则 Windows 的 SO_REUSEADDR 会让新旧实例抢同一个
#      端口，新连接被后绑定的那个接管，很容易出现「服务明明开着但连的不是它」）
#   2) 启动 Flask 服务并等到它真的能响应
#   3) 重建 adb reverse 隧道 —— 这是最常被忽略的一步：游戏内是
#      http://127.0.0.1:8080/，在手机上指向手机自己，必须靠 reverse 把端口
#      转发到电脑。手机重连、adb 重启、电脑休眠后这条隧道都会消失，
#      表现为「服务开着但游戏一直进不去」
#   4) 可选：把游戏拉到前台
#
# 用法：
#   pwsh -File tools\start-server.ps1              # 只起服务 + 隧道
#   pwsh -File tools\start-server.ps1 -LaunchApp   # 顺带拉起游戏
#   pwsh -File tools\start-server.ps1 -Port 8081   # 换端口（记得同步客户端配置）

param(
    [int]$Port = 8080,
    [string]$Serial = "24086b59",
    [string]$Adb = "F:\SoftWare\adb\adb.exe",
    [switch]$LaunchApp
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$serverDir = Join-Path $repo "server"
$python = Join-Path $serverDir ".venv\Scripts\python.exe"
$package = "air.com.lv1.hunter.iconless.localusb"

if (-not (Test-Path $python)) {
    throw "找不到虚拟环境 Python：$python"
}

function Test-Server {
    param([int]$Port)
    try {
        $response = Invoke-WebRequest "http://127.0.0.1:$Port/data/android/zh-CN/server.xml" `
            -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

# 1) 清掉遗留实例 ------------------------------------------------------------
$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if ($owner -and $owner.ProcessName -like "python*") {
        Write-Host "[1/4] 关闭遗留服务实例 PID $($owner.Id)" -ForegroundColor Yellow
        # venv 的 python.exe 是个转发壳，真正的进程是它的子进程，两个都要停
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.ParentProcessId -eq $owner.Id } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $owner.Id -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Milliseconds 800

# 2) 启动服务 ----------------------------------------------------------------
Write-Host "[2/4] 启动服务 http://127.0.0.1:$Port" -ForegroundColor Cyan
$logFile = Join-Path $env:TEMP "pet-hunter-server-$Port.log"
$process = Start-Process -FilePath $python `
    -ArgumentList "-m", "pet_hunter_server", "--host", "127.0.0.1", "--port", "$Port" `
    -WorkingDirectory $serverDir `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError "$logFile.err" `
    -PassThru -WindowStyle Hidden

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Server -Port $Port) { $ready = $true; break }
    if ($process.HasExited) { break }
}
if (-not $ready) {
    Write-Host "服务没起来，看日志：" -ForegroundColor Red
    Write-Host "  $logFile" -ForegroundColor Red
    Write-Host "  $logFile.err" -ForegroundColor Red
    if (Test-Path "$logFile.err") { Get-Content "$logFile.err" -Tail 20 }
    exit 1
}
Write-Host "      服务就绪，PID $($process.Id)，日志 $logFile" -ForegroundColor Green

# 3) 重建 adb reverse 隧道 ---------------------------------------------------
Write-Host "[3/4] 重建 adb reverse 隧道" -ForegroundColor Cyan
if (-not (Test-Path $Adb)) {
    Write-Host "      找不到 adb：$Adb（跳过隧道，手机将连不上）" -ForegroundColor Yellow
} else {
    & $Adb reconnect 2>&1 | Out-Null
    Start-Sleep -Seconds 3
    $devices = & $Adb devices | Select-String "$Serial\s+device"
    if (-not $devices) {
        Write-Host "      设备 $Serial 不在线，请检查数据线/授权（跳过隧道）" -ForegroundColor Yellow
    } else {
        # 先移除再添加，避免旧规则残留指向已失效的端口
        & $Adb -s $Serial reverse --remove-all 2>&1 | Out-Null
        & $Adb -s $Serial reverse "tcp:$Port" "tcp:$Port" 2>&1 | Out-Null
        $tunnels = & $Adb -s $Serial reverse --list 2>&1
        if ($tunnels -match "tcp:$Port") {
            Write-Host "      隧道已建立：$tunnels" -ForegroundColor Green
        } else {
            Write-Host "      隧道建立失败，请重插数据线后重试" -ForegroundColor Red
        }
    }
}

# 4) 可选拉起游戏 ------------------------------------------------------------
if ($LaunchApp) {
    Write-Host "[4/4] 拉起游戏" -ForegroundColor Cyan
    & $Adb -s $Serial shell am force-stop $package 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    & $Adb -s $Serial shell am start -n "$package/$package.AIRAppEntry" 2>&1 | Out-Null
    # 游戏启动过程中会重连一次网络，隧道在这之后再确认一遍更保险
    Start-Sleep -Seconds 10
    & $Adb -s $Serial reverse "tcp:$Port" "tcp:$Port" 2>&1 | Out-Null
    Write-Host "      已启动，隧道已复核" -ForegroundColor Green
} else {
    Write-Host "[4/4] 跳过拉起游戏（加 -LaunchApp 可直接进游戏）" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "完成。若游戏仍显示网络错误，按顺序检查：" -ForegroundColor Cyan
Write-Host "  1. adb devices 里设备是否为 device 状态"
Write-Host "  2. adb reverse --list 是否有 tcp:$Port"
Write-Host "  3. 客户端 data/android/zh-CN/server.xml 的 url 端口是否与 $Port 一致"
