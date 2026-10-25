# 桌面预览（AIR ADL）——不打包 APK 就能看客户端改动

归档时间：2026-10-25。起因：改一次 SWF 就要 `adt` 打 43MB APK + `adb install`，一轮至少 1~2 分钟，
按钮位置、弹窗布局、协议跳转这类问题根本没法快速试。现在改成**桌面先看，真机只做里程碑验收**。

## 结论

AIR SDK 自带的 `adl64.exe` 能在 Windows 上直接跑这个 SWF，**不打包、不装机、2~3 秒出画面**。

前提（都已满足，换 SDK 或改描述文件时需复查）：

- `PetHunter-app.xml` 里没有 `<extensions>`（没有 ANE）；
- 没有 `<supportedProfiles>mobileDevice</supportedProfiles>` 限制；
- SWF 原生舞台是 **640×960**，桌面窗口也用 640×960 时，按钮/弹窗位置与真机一致；
  用 480×854 会偏（曾踩过）。

## 用法

```powershell
cd F:\git\PetHunterG\client\air51-repack

# 1) 预览当前构建产物 build\input-explore\APetHunter.swf（不存在则退回 src\APetHunter.swf）
powershell -ExecutionPolicy Bypass -File .\dev-desktop.ps1

# 2) 先跑 FFDec 重建补丁（约 40 秒），再自动弹预览
powershell -ExecutionPolicy Bypass -File .\dev-desktop.ps1 -Build

# 3) 直接看某个已打好的产物
powershell -ExecutionPolicy Bypass -File .\dev-desktop.ps1 -Swf build\input-explore\APetHunter-hire.swf

# 4) 换窗口尺寸（默认 640x960）
powershell -ExecutionPolicy Bypass -File .\dev-desktop.ps1 -Width 480 -Height 854
```

## 截图（给用户看画面，不用碰手机）

预览窗口开起来后，用 `tools/preview-shot.ps1` 抓图归档：

```powershell
cd F:\git\PetHunterG
powershell -ExecutionPolicy Bypass -File .\tools\preview-shot.ps1 -Name login
powershell -ExecutionPolicy Bypass -File .\tools\preview-shot.ps1 -Title "PetHunterG desktop preview" -Name bag-popup
powershell -ExecutionPolicy Bypass -File .\tools\preview-shot.ps1 -ClientArea -Name main-home
```

- 默认存到 `docs\preview\<yyyy-MM-dd>\<HHmmss>-<Name>.png`（该目录被 `.gitignore` 忽略，本地产物）。
- 脚本会先还原窗口并置前，再按**物理像素**抓；输出 `非黑占比`，接近 0% 说明窗口没画出来（不是游戏黑屏）。
- 抓完在回复里直接内联：`![背包弹窗](docs/preview/2026-10-25/131500-bag-popup.png)`。

## 多窗口（每个 lane 一个 UI）

并行开发时每个 lane 有自己的服务端口、构建目录和窗口标题，互不干扰：

| lane | 服务端口 | 窗口标题 | 构建目录 |
|---|---|---|---|
| main | 8080 | `PetHunterG preview [main]` | `build\desktop-dev-main\` |
| b1 | 8081 | `PetHunterG preview [b1]` | `build\desktop-dev-b1\` |
| b2 | 8082 | `PetHunterG preview [b2]` | `build\desktop-dev-b2\` |

- 同时最多 3 个窗口（每个 ADL 约 200MB）；第 4 个先停一个。
- 抓图按标题精确匹配：`preview-shot.ps1 -Title "PetHunterG preview [b1]"`。
- **现状**：`dev-desktop.ps1` 还是单实例（固定 8080、固定 `build\desktop-dev`、启动前 `Stop-Process adl64`）。
  多窗口参数（`-Label` / `-Port` / `-NoKill` / `-DevDir`）与 `tools/lane.ps1` 在看板 **T01 / T02**，
  落地后本节命令才成立；在那之前只能一次开一个窗口。

## 脚本做了什么（`dev-desktop.ps1`）

1. 选源：`-Swf` > `build\input-explore\APetHunter.swf` > `src\APetHunter.swf`；
2. **复制**到 `build\desktop-dev\APetHunter.swf`——`src\*.swf` 永不修改；
3. 把服务器基址改写成本机 Flask：
   - `http://43.173.99.241:8080`（远程构建）→ `http://127.0.0.1:8080`
   - 原始客户端 4 个 `http://123.196.114.169/`、`.177`、`.185`、`.196` → 同样改本机
   - 已经指向 `127.0.0.1:8080` 则跳过；
   - 都不认识时只告警，并在输出里列出看到的 IP，不乱改；
4. `build\desktop-dev\data` 用**目录联接**指向 `src\data`（20+MB 资源不重复复制）；
5. 生成桌面用 `PetHunter-desktop.xml`（Android 那份不动），窗口 640×960；
6. 关掉上一个 `adl64`，启动新窗口；trace 输出在 `build\desktop-dev\adl.log` 和 `adl.log.err`。

## 和打包流程的关系

```
改 AS3 / 补丁脚本
   └─ rebuild-client-patches.py  →  build\input-explore\APetHunter.swf
        └─ dev-desktop.ps1 -Build  →  桌面窗口（秒级确认布局/协议）
             └─ 确认后再 adt 打包 + adb 装机（只在里程碑或真机专属问题时）
```

桌面版直连 `127.0.0.1:8080`，**不需要 `adb reverse`**，比真机还省一步；前提是本机 Flask 在跑
（`server/.venv/Scripts/python.exe -m pet_hunter_server --host 127.0.0.1 --port 8080`）。

## 边界（不能替代真机）

- 触屏手势、Android 返回键、系统安装/权限弹窗、ARM 渲染差异、性能与发热；
- 真机专属 API 的返回值（屏幕 DPI、机型判断）在桌面会不同；
- 因此：**日常 UI/AS3/协议用桌面，装机只在里程碑或怀疑平台差异时做。**

## 排错

| 现象 | 处理 |
|---|---|
| 窗口不出现 / 一闪而过 | 看 `build\desktop-dev\adl.log` 与 `adl.log.err`（`trace()` 输出在 `.err`） |
| 弹出 "ActionScript error" 对话框 | SWF 里的 AS3 异常，不是预览的问题；按 #错误号查补丁源码 |
| 按钮/弹窗位置和真机不一致 | 确认窗口是 640×960（SWF 原生舞台） |
| 连不上服务器 | 先 `curl http://127.0.0.1:8080/health`；再看脚本输出里是否提示"未知服务器基址，未改写" |

## 已验证记录

- 2026-10-25 13:20：`dev-desktop.ps1` 默认路径跑通，窗口标题 `PetHunterG desktop preview`，
  日志加载 `data/skin1.swf`、`data/unique.swf` 等，可进入游戏界面并与本机 Flask 通信。
- 2026-10-25 13:30：窗口尺寸改为 640×960 后，弹窗与按钮位置和真机一致（480×854 会偏）。
- 同次发现并修复：`patches/BagListUI-use-popup.as3` 里 `flash.utils.setTimeout(...)` 用了全限定名，
  AVM2 报 `ReferenceError: Error #1065: Variable flash is not defined`（`BagListUI/onUseConfirm`）。
  包级函数必须 `import flash.utils.setTimeout;` 后裸调 `setTimeout(...)`。
