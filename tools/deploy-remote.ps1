# 宠物猎人G —— 部署到公网服务器
#
# 把本地服务端打包、上传、装成 systemd 服务，并用 nginx 反代到公网端口。
#
# 设计约束（不要改）：
#   * 服务端 CLI 只允许绑回环/内网地址，所以 Flask 一律跑 127.0.0.1，
#     公网入口交给 nginx 反代 —— 这样也不会去抢服务器上已有的 80/443。
#   * 配置表通过 PETHUNTER_CONFIG_ROOT 指定，不依赖仓库目录结构。
#   * 存档是 server/instance/game.sqlite3 的一份**拷贝**；部署后进度以服务器上的为准。
#
# 用法（在本机仓库根目录执行）：
#   pwsh -File tools\deploy-remote.ps1 -ServerHost 43.173.99.241 -Port 8080
# 需要环境变量 VPS_PWD 提供 SSH 密码；脚本不会把密码写进任何文件。

param(
    [Parameter(Mandatory = $true)][string]$ServerHost,
    [int]$Port = 8080,
    [int]$LocalAppPort = 8081,
    [string]$User = "root",
    [string]$RemoteDir = "/opt/pethunter",
    [switch]$SkipApk,
    # 默认**不**用本机存档覆盖远端：部署后进度以服务器为准，误覆盖会丢档。
    # 只有首次部署或明确要回迁本机存档时才加 -WithSave。
    [switch]$WithSave
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if (-not $env:VPS_PWD) { throw "请先设置环境变量 VPS_PWD（SSH 密码）" }

$python = Join-Path $repo "server\.venv\Scripts\python.exe"
$stage = Join-Path $env:TEMP "pethunter-deploy"
$zip = Join-Path $env:TEMP "pethunter-deploy.zip"

# 1) 打包 ---------------------------------------------------------------
Write-Host "[1/5] 打包服务端 + 配置表 + 存档" -ForegroundColor Cyan
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path "$stage\config-data\zh-CN\config" -Force | Out-Null
New-Item -ItemType Directory -Path "$stage\instance" -Force | Out-Null
Copy-Item (Join-Path $repo "server\pet_hunter_server") -Destination $stage -Recurse
Copy-Item (Join-Path $repo "client\air51-repack\src\data\zh-CN\config\*.txt") -Destination "$stage\config-data\zh-CN\config"
Copy-Item (Join-Path $repo "client\air51-repack\src\data\skin.txt") -Destination "$stage\config-data"
if ($WithSave) {
    Copy-Item (Join-Path $repo "server\instance\game.sqlite3") -Destination "$stage\instance"
    Write-Host "      已包含本机存档（-WithSave）" -ForegroundColor Yellow
} else {
    Write-Host "      不含存档：部署后保留服务器上现有进度" -ForegroundColor Green
}
Remove-Item "$stage\pet_hunter_server\__pycache__" -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "$stage\*" -DestinationPath $zip -Force
Write-Host "      已生成 $([math]::Round((Get-Item $zip).Length/1KB,1)) KB" -ForegroundColor Green

# 2) 上传并安装 ---------------------------------------------------------
Write-Host "[2/5] 上传并安装到 $RemoteDir" -ForegroundColor Cyan
$env:DEPLOY_HOST = $ServerHost
$env:DEPLOY_PORT = "$Port"
$env:DEPLOY_APP_PORT = "$LocalAppPort"
$env:DEPLOY_USER = $User
$env:DEPLOY_DIR = $RemoteDir
$env:DEPLOY_ZIP = $zip

@'
import os, posixpath, paramiko

host = os.environ["DEPLOY_HOST"]; user = os.environ["DEPLOY_USER"]
port = os.environ["DEPLOY_PORT"]; app_port = os.environ["DEPLOY_APP_PORT"]
remote = os.environ["DEPLOY_DIR"]; zip_path = os.environ["DEPLOY_ZIP"]

c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(host, username=user, password=os.environ["VPS_PWD"], timeout=25,
          look_for_keys=False, allow_agent=False)

def run(cmd, timeout=600):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    o = out.read().decode(errors="replace").strip()
    e = err.read().decode(errors="replace").strip()
    if o: print("      " + o.replace("\n", "\n      "))
    if e and "DeprecationWarning" not in e: print("      [stderr] " + e[:400])
    return o

sftp = c.open_sftp()
sftp.put(zip_path, "/tmp/pethunter-deploy.zip")
sftp.close()

run("which unzip >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq unzip) 2>&1 | tail -1")
# 远端存档必须保住：先备份到 /tmp，重装后还原（除非本次带了新存档）
run(f"[ -f {remote}/instance/game.sqlite3 ] && cp -f {remote}/instance/game.sqlite3 /tmp/ph-save.sqlite3 || true")
run(f"rm -rf {remote} && mkdir -p {remote} && cd {remote} && unzip -q /tmp/pethunter-deploy.zip")
run(f"mkdir -p {remote}/instance && "
    f"if [ -f /tmp/ph-save.sqlite3 ]; then cp -f /tmp/ph-save.sqlite3 {remote}/instance/game.sqlite3; "
    f"echo 'kept remote save'; fi")
run("DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3.12-venv 2>&1 | tail -1")
run(f"python3 -m venv {remote}/.venv && {remote}/.venv/bin/pip install -q --upgrade pip "
    f"&& {remote}/.venv/bin/pip install -q flask")

# server.xml the client fetches — must advertise the PUBLIC url
run(f"mkdir -p {remote}/fixtures/data/android")
xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n'
       f'  <server id="1" name="PetHunter Remote" icon="clip_back_login" n="0" '
       f'url="http://{host}:{port}/" />\n</config>\n')
sftp = c.open_sftp()
with sftp.file(f"{remote}/fixtures/data/android/server.xml", "w") as fh:
    fh.write(xml)

unit = f"""[Unit]
Description=Pet Hunter G server
After=network.target

[Service]
Type=simple
WorkingDirectory={remote}
Environment=PETHUNTER_CONFIG_ROOT={remote}/config-data
ExecStart={remote}/.venv/bin/python -m pet_hunter_server --host 127.0.0.1 --port {app_port}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
with sftp.file("/etc/systemd/system/pethunter.service", "w") as fh:
    fh.write(unit)

# nginx front door on the public port (never touches the existing 80/443 sites)
nginx = f"""server {{
    listen {port};
    server_name _;
    client_max_body_size 8m;
    location / {{
        proxy_pass http://127.0.0.1:{app_port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;
    }}
}}
"""
with sftp.file("/www/server/panel/vhost/nginx/pethunter.conf", "w") as fh:
    fh.write(nginx)
sftp.close()

run("systemctl daemon-reload && systemctl enable pethunter >/dev/null 2>&1; systemctl restart pethunter")
run("nginx -t 2>&1 | tail -1 && nginx -s reload")
run(f"ufw allow {port}/tcp >/dev/null 2>&1; ufw status | grep {port} || true")
import time; time.sleep(4)
print("      local  :", run(f"curl -s -m 5 http://127.0.0.1:{port}/data/android/zh-CN/server.xml | tr -d '\\n'")[:80])
print("      status :", run("systemctl is-active pethunter"))
c.close()
'@ | Set-Content -Encoding UTF8 (Join-Path $env:TEMP "ph_deploy.py")
& $python (Join-Path $env:TEMP "ph_deploy.py")
Remove-Item (Join-Path $env:TEMP "ph_deploy.py")

# 3) 公网验证 -----------------------------------------------------------
Write-Host "[3/5] 公网连通性验证" -ForegroundColor Cyan
try {
    $r = Invoke-WebRequest "http://${ServerHost}:${Port}/data/android/zh-CN/server.xml" -UseBasicParsing -TimeoutSec 10
    Write-Host "      HTTP $($r.StatusCode) OK" -ForegroundColor Green
} catch {
    Write-Host "      公网访问失败：请到云控制台安全组放行 TCP $Port" -ForegroundColor Red
    Write-Host "      $($_.Exception.Message)" -ForegroundColor Red
}

# 4) 重建 APK（可选）----------------------------------------------------
if (-not $SkipApk) {
    Write-Host "[4/5] 重建指向公网的 APK" -ForegroundColor Cyan
    $repack = Join-Path $repo "client\air51-repack"
    $work = Join-Path $repack "build\input-remote"
    if (Test-Path $work) { Remove-Item $work -Recurse -Force }
    Copy-Item (Join-Path $repack "build\input-localusb") $work -Recurse
    & $python (Join-Path $repack "patch_swf_url.py") `
        (Join-Path $work "APetHunter.swf") (Join-Path $work "APetHunter-new.swf") `
        --replace "http://127.0.0.1:$LocalAppPort=http://${Host}:${Port}" --replace-all 2>&1 | Out-Null
    if (-not (Test-Path (Join-Path $work "APetHunter-new.swf"))) {
        # 本地包里的地址可能是别的端口，按实际值再试一次
        throw "SWF 地址补丁失败：请确认包内 URL 与 -Port 一致"
    }
    Move-Item (Join-Path $work "APetHunter-new.swf") (Join-Path $work "APetHunter.swf") -Force
    Write-Host "      SWF 已指向 http://${Host}:${Port}" -ForegroundColor Green
}

# 5) 收尾 ---------------------------------------------------------------
Write-Host "[5/5] 完成" -ForegroundColor Cyan
Write-Host "  服务端：$RemoteDir（systemd: pethunter）"
Write-Host "  公网入口：http://${ServerHost}:${Port}/"
Write-Host "  APK：client\air51-repack\build\out\PetHunterG-Remote.apk（需用 adt 打包并安装）"
Write-Host "  注意：存档是拷贝，部署后以服务器上的为准。"
