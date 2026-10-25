# Lane scaffolding: one isolated dev environment per task.
#
# A lane is: a git worktree + a branch + a Flask port + its own save file + its
# own desktop preview window. Several lanes can run at the same time, so two
# backend tasks can be developed and clicked through in parallel without
# touching each other or the main save.
#
#   pwsh tools\lane.ps1 new   b1 feat/hero-growth          # worktree + branch, port 8081
#   pwsh tools\lane.ps1 start b1 [-CopySave] [-NoUi] [-Build]
#   pwsh tools\lane.ps1 shoot b1 -Name bag-popup           # docs/preview/<day>/b1-bag-popup.png
#   pwsh tools\lane.ps1 stop  b1
#   pwsh tools\lane.ps1 list
#
# Note: `start` launches the window in a detached process and waits on the pid
# file, so it always returns. Never wrap `dev-desktop.ps1` in `& pwsh ...` and
# wait for it from an agent shell: adl64 outlives it and keeps the inherited
# stdout handle open, which makes the caller hang after printing everything.
#
# Rules (docs/AGENTS.md):
#   - worktrees live under .worktrees<name> inside the repo (git-ignored);
#   - each lane has its own port (8081..8089) and its own server/instance DB;
#   - only this lane's processes are started/stopped: never "Stop-Process adl64".

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('new', 'start', 'stop', 'shoot', 'list', 'remove')]
    [string]$Command,

    [Parameter(Position = 1)]
    [string]$Name = '',

    [Parameter(Position = 2)]
    [string]$Branch = '',

    [int]$Port = 0,
    [string]$Shot = 'shot',
    [switch]$CopySave,
    [switch]$NoUi,
    [switch]$Build,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$lanesDir = Join-Path $root '.worktrees'
$manifest = Join-Path $lanesDir 'lanes.json'
$venvPython = Join-Path $root 'server\.venv\Scripts\python.exe'
$devDesktop = Join-Path $root 'client\air51-repack\dev-desktop.ps1'
$shotTool = Join-Path $root 'tools\preview-shot.ps1'
$mainSwf = Join-Path $root 'client\air51-repack\build\input-explore\APetHunter.swf'

function Read-Lanes {
    if (-not (Test-Path $manifest)) { return @{} }
    try {
        $raw = Get-Content $manifest -Raw -Encoding UTF8
        if ([string]::IsNullOrWhiteSpace($raw)) { return @{} }
        $obj = $raw | ConvertFrom-Json
        $table = @{}
        foreach ($property in $obj.PSObject.Properties) { $table[$property.Name] = $property.Value }
        return $table
    } catch {
        throw "cannot parse ${manifest}: $($_.Exception.Message)"
    }
}

function Write-Lanes($table) {
    New-Item -ItemType Directory -Force -Path $lanesDir | Out-Null
    $table | ConvertTo-Json -Depth 5 | Set-Content -Path $manifest -Encoding UTF8
}

function Get-Lane([string]$laneName) {
    $lanes = Read-Lanes
    if (-not $lanes.ContainsKey($laneName)) { throw "unknown lane '$laneName' (run: lane.ps1 list)" }
    return $lanes[$laneName]
}

function Get-LaneDir([string]$laneName) { Join-Path $lanesDir $laneName }

function Get-FreeLanePort($lanes, [int]$wanted) {
    if ($wanted -gt 0) { return $wanted }
    $used = @($lanes.Values | ForEach-Object { [int]$_.port })
    foreach ($candidate in 8081..8089) {
        if ($used -notcontains $candidate) { return $candidate }
    }
    throw "no free lane port in 8081..8089"
}

function Get-ListeningProcess([int]$listenPort) {
    $connection = Get-NetTCPConnection -LocalPort $listenPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $connection) { return $null }
    return Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
}

function Wait-Health([int]$listenPort, [int]$seconds = 20) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:$listenPort/health" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return $true }
        } catch { Start-Sleep -Milliseconds 400 }
    }
    return $false
}

function Invoke-Adl([string]$laneName, [int]$listenPort, [string]$laneDir) {
    $swf = Join-Path $laneDir 'client\air51-repack\build\input-explore\APetHunter.swf'
    if (-not (Test-Path $swf)) {
        if (-not (Test-Path $mainSwf)) {
            Write-Host "[!] no SWF to preview (lane has no build, and main has none either)" -ForegroundColor Yellow
            return
        }
        Write-Host "[i] lane has no client build yet; previewing main's build\input-explore\APetHunter.swf" -ForegroundColor Cyan
        $swf = $mainSwf
    }
    $arguments = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $devDesktop,
        '-Label', $laneName, '-Port', "$listenPort", '-Swf', $swf,
        '-DevDir', (Join-Path $laneDir "client\air51-repack\build\desktop-dev-$laneName"),
        '-DataDir', (Join-Path $laneDir 'client\air51-repack\src\data')
    )
    if ($Build) { $arguments += '-Build' }

    # Launch the preview in a separate process and wait on its pid file instead of
    # on the process: adl64 outlives the launcher, and any caller that waits for the
    # launcher's inherited stdout handle never sees EOF (symptom: the command hangs
    # after printing everything, because a long-lived GUI child holds the pipe).
    $devDir = Join-Path $laneDir "client\air51-repack\build\desktop-dev-$laneName"
    Start-Process -FilePath 'pwsh' -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden | Out-Null

    $title = "PetHunterG preview [$laneName]"
    $pidFile = Join-Path $devDir 'adl.pid'
    $deadline = (Get-Date).AddSeconds(30)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        if (-not (Test-Path $pidFile)) { continue }
        $raw = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not ($raw -as [int])) { continue }
        $ui = Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue
        if ($ui -and $ui.MainWindowTitle -eq $title) { $ready = $true; break }
    }
    if ($ready) {
        Write-Host "[ok] window ready: $title" -ForegroundColor Green
    } else {
        Write-Host "[!] window not confirmed within 30s; see $(Join-Path $devDir 'adl.log.err')" -ForegroundColor Yellow
    }
}

switch ($Command) {
    'list' {
        $lanes = Read-Lanes
        if ($lanes.Count -eq 0) { Write-Host "no lanes yet (lane.ps1 new <name> <branch>)" ; break }
        $lanes.GetEnumerator() | Sort-Object Name | ForEach-Object {
            $laneName = $_.Key
            $info = $_.Value
            $listenPort = [int]$info.port
            $proc = Get-ListeningProcess $listenPort
            $health = if ($proc) { try { (Invoke-WebRequest "http://127.0.0.1:$listenPort/health" -UseBasicParsing -TimeoutSec 2).StatusCode } catch { 'down' } } else { '-' }
            $devDir = Join-Path (Get-LaneDir $laneName) "client\air51-repack\build\desktop-dev-$laneName"
            $uiPid = '-'
            $pidFile = Join-Path $devDir 'adl.pid'
            if (Test-Path $pidFile) {
                $candidate = Get-Process -Id ([int](Get-Content $pidFile | Select-Object -First 1)) -ErrorAction SilentlyContinue
                if ($candidate -and $candidate.ProcessName -eq 'adl64') { $uiPid = $candidate.Id }
            }
            [pscustomobject]@{
                lane   = $laneName
                port   = $listenPort
                health = $health
                flask  = if ($proc) { $proc.Id } else { '-' }
                ui     = $uiPid
                branch = $info.branch
                save   = if (Test-Path (Join-Path (Get-LaneDir $laneName) 'server\instance\game.sqlite3')) { 'yes' } else { '-' }
            }
        } | Format-Table -AutoSize | Out-String | Write-Host
    }

    'new' {
        if (-not $Name) { throw "usage: lane.ps1 new <name> <branch> [-Port 8081]" }
        if (-not $Branch) { throw "usage: lane.ps1 new <name> <branch> [-Port 8081]" }
        $lanes = Read-Lanes
        if ($lanes.ContainsKey($Name)) { throw "lane '$Name' already exists (lane.ps1 list)" }
        $laneDir = Get-LaneDir $Name
        if (Test-Path $laneDir) { throw "directory already exists: $laneDir" }
        $listenPort = Get-FreeLanePort $lanes $Port
        if (Get-ListeningProcess $listenPort) { throw "port $listenPort is already listening" }

        & git -C $root worktree add $laneDir -b $Branch main
        if ($LASTEXITCODE -ne 0) { throw "git worktree add failed (exit $LASTEXITCODE)" }

        New-Item -ItemType Directory -Force -Path (Join-Path $laneDir 'logs') | Out-Null
        $lanes[$Name] = [pscustomobject]@{
            branch  = $Branch
            port    = $listenPort
            created = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
            dir     = $laneDir
        }
        Write-Lanes $lanes
        Write-Host "[ok] lane $Name -> $laneDir  branch=$Branch port=$listenPort" -ForegroundColor Green
    }

    'start' {
        if (-not $Name) { throw "usage: lane.ps1 start <name> [-CopySave] [-NoUi]" }
        $info = Get-Lane $Name
        $laneDir = Get-LaneDir $Name
        $listenPort = [int]$info.port
        if (-not (Test-Path $laneDir)) { throw "worktree missing: $laneDir (was it removed by hand?)" }

        $savePath = Join-Path $laneDir 'server\instance\game.sqlite3'
        if ($CopySave) {
            $mainSave = Join-Path $root 'server\instance\game.sqlite3'
            if (-not (Test-Path $mainSave)) { throw "main save not found: $mainSave" }
            $running = Get-ListeningProcess $listenPort
            if ($running) { throw "lane $Name is already running; stop it before -CopySave (would overwrite an open DB)" }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $savePath) | Out-Null
            Copy-Item $mainSave $savePath -Force
            foreach ($suffix in '-wal', '-shm') {
                if (Test-Path "$mainSave$suffix") { Copy-Item "$mainSave$suffix" "$savePath$suffix" -Force }
            }
            Write-Host "[ok] copied main save into lane $Name" -ForegroundColor Green
        }

        $existing = Get-ListeningProcess $listenPort
        if ($existing) {
            if (Wait-Health $listenPort 3) {
                Write-Host "[i] port $listenPort already serves /health (pid $($existing.Id)); reusing" -ForegroundColor Cyan
            } else {
                throw "port $listenPort is held by pid $($existing.Id) ($($existing.ProcessName)) but /health does not answer"
            }
        } else {
            $logDir = Join-Path $laneDir 'logs'
            New-Item -ItemType Directory -Force -Path $logDir | Out-Null
            $out = Join-Path $logDir 'server.log'
            $err = Join-Path $logDir 'server.err.log'
            $proc = Start-Process -FilePath $venvPython `
                -ArgumentList @('-m', 'pet_hunter_server', '--host', '127.0.0.1', '--port', "$listenPort") `
                -WorkingDirectory (Join-Path $laneDir 'server') `
                -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
            if (Wait-Health $listenPort) {
                Write-Host "[ok] lane $Name flask pid=$($proc.Id) http://127.0.0.1:$listenPort  log=$out" -ForegroundColor Green
            } else {
                Write-Host "[x] lane $Name flask did not answer /health; see $err" -ForegroundColor Red
                exit 1
            }
        }

        if (-not $NoUi) { Invoke-Adl $Name $listenPort $laneDir }
    }

    'shoot' {
        if (-not $Name) { throw "usage: lane.ps1 shoot <name> [-Shot shot-name]" }
        $info = Get-Lane $Name
        $null = $info
        $title = "PetHunterG preview [$Name]"
        & pwsh -NoProfile -File $shotTool -Title $title -Name "$Name-$Shot" -Width 640 -Height 960 -ClientArea
        if ($LASTEXITCODE -ne 0) { throw "window '$title' not found (lane.ps1 start $Name -Ui first?)" }
    }

    'stop' {
        if (-not $Name) { throw "usage: lane.ps1 stop <name>" }
        $info = Get-Lane $Name
        $listenPort = [int]$info.port

        $proc = Get-ListeningProcess $listenPort
        if ($proc) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Write-Host "[ok] stopped flask pid=$($proc.Id) on port $listenPort" -ForegroundColor Green
        } else {
            Write-Host "[i] nothing listening on port $listenPort" -ForegroundColor Cyan
        }

        $devDir = Join-Path (Get-LaneDir $Name) "client\air51-repack\build\desktop-dev-$Name"
        $pidFile = Join-Path $devDir 'adl.pid'
        if (Test-Path $pidFile) {
            $uiPid = [int](Get-Content $pidFile | Select-Object -First 1)
            $uiProc = Get-Process -Id $uiPid -ErrorAction SilentlyContinue
            if ($uiProc -and $uiProc.ProcessName -eq 'adl64') {
                Stop-Process -Id $uiPid -Force -ErrorAction SilentlyContinue
                Write-Host "[ok] closed window pid=$uiPid ($Name)" -ForegroundColor Green
            }
            Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        }
    }

    'remove' {
        if (-not $Name) { throw "usage: lane.ps1 remove <name> [-Force]" }
        $info = Get-Lane $Name
        $laneDir = Get-LaneDir $Name
        $proc = Get-ListeningProcess ([int]$info.port)
        if ($proc -and -not $Force) { throw "lane $Name still running on port $($info.port); stop it first (or -Force)" }
        if ($proc) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }

        $devDir = Join-Path $laneDir "client\air51-repack\build\desktop-dev-$Name"
        $pidFile = Join-Path $devDir 'adl.pid'
        if (Test-Path $pidFile) {
            $uiPid = [int](Get-Content $pidFile | Select-Object -First 1)
            $uiProc = Get-Process -Id $uiPid -ErrorAction SilentlyContinue
            if ($uiProc -and $uiProc.ProcessName -eq 'adl64') { Stop-Process -Id $uiPid -Force -ErrorAction SilentlyContinue }
        }

        $lanes = Read-Lanes
        $branch = $info.branch
        $dataLink = Join-Path $devDir 'data'
        $linkItem = Get-Item $dataLink -Force -ErrorAction SilentlyContinue
        if ($linkItem -and $linkItem.LinkType -eq 'Junction') {
            # 必须先用 rmdir 拆掉联接本身：`git worktree remove` 的递归删除会跟着
            # 联接进目标目录，曾把主仓库 client/air51-repack/src/data 清空。
            cmd /c rmdir "$dataLink" | Out-Null
        }
        & git -C $root worktree remove $laneDir --force
        if ($LASTEXITCODE -ne 0) { throw "git worktree remove failed (exit $LASTEXITCODE)" }
        $lanes.Remove($Name)
        Write-Lanes $lanes
        Write-Host "[ok] removed lane $Name (branch $branch kept; delete with: git branch -D $branch)" -ForegroundColor Green
    }
}

