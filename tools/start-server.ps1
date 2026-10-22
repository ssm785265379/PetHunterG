# 宠物猎人G —— 本地服务一键启动 / 连接修复
#
# 把每次重连都要手动做的事固化下来。脚本是幂等的：服务已经在跑就不会重启它，
# 只修隧道；需要强杀重开时加 -Restart。
#
# 顺序很重要，每一步都对应一个真实踩过的坑：
#   1) 服务没在跑才启动，并等到它真的能响应（不是盲目 sleep）
#   2) 设备可能显示 offline —— 这是最常见的「进不去」原因，自动 reconnect 重试，
#      还不行就 adb kill-server / start-server 重来
#   3) 重建 adb reverse 隧道 —— 游戏内地址是 http://127.0.0.1:8080/，在手机上
#      指向手机自己，必须靠 reverse 把端口转发到电脑。手机重连、adb 重启、
#      电脑休眠后这条隧道都会静默消失，现象就是「服务开着但游戏一直网络错误」
#   4) 可选把游戏拉到前台，并在启动后再复核一次隧道（游戏启动会重连网络）
#
# 用法：
#   pwsh -File tools\start-server.ps1                 # 服务在跑就只修隧道
#   pwsh -File tools\start-server.ps1 -LaunchApp      # 顺带把游戏拉到前台
#   pwsh -File tools\start-server.ps1 -Restart        # 强杀旧实例重开
#   pwsh -File tools\start-server.ps1 -Port 8081      # 换端口（记得同步客户端配置）

param(
    [int]$Port = 8080,
    [string]$Serial = "24086b59",
    [string]$Adb = "F:\SoftWare\adb\adb.exe",
    [switch]$LaunchApp,
    [switch]$Restart
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$serverDir = Join-Path $repo "server"
$python = Join-Path $serverDir ".venv\Scripts\python.exe"
$package = "air.com.lv1.hunter.iconless.localusb"
$logFile = Join-Path $env:TEMP "pet-hunter-server-$Port.log"
$errFile = "$logFile.err"

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

function Stop-ServerInstances {
    param([int]$Port)
    $stopped = 0
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        if ($owner -and $owner.ProcessName -like "python*") {
            # venv 的 python.exe 是个转发壳，真正的进程是它的子进程，两个都要停
            Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
                Where-Object { $_.ParentProcessId -eq $owner.Id } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Stop-Process -Id $owner.Id -Force -ErrorAction SilentlyContinue
            $stopped++
        }
    }
    # 端口空闲了也可能有壳残留，按命令行再兜一次
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*pet_hunter_server*--port $Port*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $stopped++ }
    return $stopped
}

function Wait-ForDevice {
    param([string]$Serial, [int]$Attempts = 3)
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $state = (& $Adb devices 2>&1 | Select-String "^$Serial\s+(\S+)")
        if ($state -and $state.Matches[0].Groups[1].Value -eq "device") {
            return $true
        }
        Write-Host "      设备未就绪（第 $attempt 次），执行 adb reconnect" -ForegroundColor Yellow
        & $Adb reconnect 2>&1 | Out-Null
        Start-Sleep -Seconds 4
    }
    # 软重连失败时，重启 adb 服务端通常能救回来
    Write-Host "      reconnect 无效，重启 adb server" -ForegroundColor Yellow
    & $Adb kill-server 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    & $Adb start-server 2>&1 | Out-Null
    Start-Sleep -Seconds 4
    $state = (& $Adb devices 2>&1 | Select-String "^$Serial\s+(\S+)")
    return ($state -and $state.Matches[0].Groups[1].Value -eq "device")
}

# 1) 服务 ------------------------------------------------------------------
if ($Restart) {
    Write-Host "[1/4] 强制重启：先停掉旧实例" -ForegroundColor Cyan
    $null = Stop-ServerInstances -Port $Port
    Start-Sleep -Milliseconds 800
}

if (Test-Server -Port $Port) {
    Write-Host "[1/4] 服务已在 $Port 端口正常响应，跳过启动" -ForegroundColor Green
} else {
    if (-not (Test-Path $python)) { throw "找不到虚拟环境 Python：$python" }
    Write-Host "[1/4] 启动服务 http://127.0.0.1:$Port" -ForegroundColor Cyan
    # 端口被别的残留实例占着会导致「启动成功但连的不是它」，先清干净
    $stopped = Stop-ServerInstances -Port $Port
    if ($stopped -gt 0) { Write-Host "      清掉 $stopped 个残留实例" -ForegroundColor Yellow; Start-Sleep -Milliseconds 800 }

    $process = Start-Process -FilePath $python `
        -ArgumentList "-m", "pet_hunter_server", "--host", "127.0.0.1", "--port", "$Port" `
        -WorkingDirectory $serverDir `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError $errFile `
        -PassThru -WindowStyle Hidden

    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Server -Port $Port) { $ready = $true; break }
        if ($process.HasExited) { break }
    }
    if (-not $ready) {
        Write-Host "服务没起来，看日志：" -ForegroundColor Red
        Write-Host "  $errFile" -ForegroundColor Red
        if (Test-Path $errFile) { Get-Content $errFile -Tail 20 }
        exit 1
    }
    Write-Host "      服务就绪，PID $($process.Id)" -ForegroundColor Green
    Write-Host "      请求日志：$errFile" -ForegroundColor DarkGray
}

# 2) 设备 ------------------------------------------------------------------
Write-Host "[2/4] 检查设备连接" -ForegroundColor Cyan
if (-not (Test-Path $Adb)) {
    Write-Host "      找不到 adb：$Adb（跳过，手机将连不上）" -ForegroundColor Red
    exit 1
}
if (-not (Wait-ForDevice -Serial $Serial)) {
    Write-Host "      设备 $Serial 仍不可用。请检查：" -ForegroundColor Red
    Write-Host "        - 数据线是否插好、是否选了「传输文件」模式"
    Write-Host "        - 手机上是否弹出了 USB 调试授权，需要点允许"
    Write-Host "        - 可尝试拔插数据线后重跑本脚本"
    exit 1
}
Write-Host "      设备在线：$Serial" -ForegroundColor Green

# 3) 隧道 ------------------------------------------------------------------
Write-Host "[3/4] 重建 adb reverse 隧道" -ForegroundColor Cyan
# 先移除再添加，避免旧规则残留指向已经失效的端口
& $Adb -s $Serial reverse --remove-all 2>&1 | Out-Null
& $Adb -s $Serial reverse "tcp:$Port" "tcp:$Port" 2>&1 | Out-Null
$tunnels = & $Adb -s $Serial reverse --list 2>&1
if ($tunnels -match "tcp:$Port") {
    Write-Host "      隧道已建立：$tunnels" -ForegroundColor Green
} else {
    Write-Host "      隧道建立失败，请重插数据线后重试" -ForegroundColor Red
    exit 1
}

# 隧道规则存在不等于手机真的连得上，从手机内部实打实请求一次才算数。
# 手机上 127.0.0.1 指的是手机自己，这条请求必须穿过 reverse 才能拿到 200。
Write-Host "      从设备内部实测连通性" -ForegroundColor Cyan
$probe = & $Adb -s $Serial shell "curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:$Port/data/android/zh-CN/server.xml" 2>&1
$probe = ("$probe" -replace '\s', '')
if ($probe -eq "200") {
    Write-Host "      设备 → 服务端 实测 200，链路真正可用" -ForegroundColor Green
} else {
    Write-Host "      设备实测失败（返回 '$probe'），游戏大概率还是进不去" -ForegroundColor Red
    Write-Host "      尝试：重插数据线 → 重新授权 USB 调试 → 重跑本脚本" -ForegroundColor Yellow
    exit 1
}

# 4) 游戏 ------------------------------------------------------------------
if ($LaunchApp) {
    Write-Host "[4/4] 拉起游戏" -ForegroundColor Cyan
    & $Adb -s $Serial shell am force-stop $package 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    & $Adb -s $Serial shell am start -n "$package/$package.AIRAppEntry" 2>&1 | Out-Null
    # 游戏启动时会重连一次网络，隧道在这之后再确认一遍更保险
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
