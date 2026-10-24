# 交接文档（当前真实状态）

写于 2026-10-24 晚。目的：换一个干净上下文也能立刻接着干，不用靠回忆。
**只写"已验证的事实"和"明确未完成的项"，不写猜测。**

## 一、当前部署 / 联调方式

用户要求：**先在本地 WiFi 联调，不推服务器**，等他通知再回到远端。手机上有两个包：

| 项 | 值 |
|---|---|
| 本地服务 | `server/.venv/Scripts/python.exe -m pet_hunter_server --host 127.0.0.1 --port 8080` |
| 本机 WiFi | `10.89.127.154` |
| 手机 WiFi | `10.89.127.80`，ADB `10.89.127.80:5555`（`adb tcpip 5555` + `adb connect`） |
| 端口转发 | `adb -s 10.89.127.80:5555 reverse tcp:8080 tcp:8080` |
| 本地联调包 | `air.com.lv1.hunter.iconless.localusb`，SWF 内 URL = `http://127.0.0.1:8080` |
| 该 APK SHA-256 | `2DB8343BFD23906DC22019DBC64D72F14A29E1AC857881FB035133289553A127` |
| 该 SWF SHA-256 | `dafd3f1e9fed018ecf3ea7285b30d5ec99fe605e7ab01d02087ae51f316cda64`（= `build/input-localusb/APetHunter.swf`） |
| 存档 | `server/instance/game.sqlite3`（本地，未上传） |
| 单测 | **165 passed**（`server/.venv/Scripts/python.exe -m pytest tests -q`） |

远端旧部署（**本轮未动**）：`/opt/pethunter`，systemd `pethunter`，`127.0.0.1:8081`，
nginx `http://43.173.99.241:8080/`，客户端 `air.com.lv1.hunter.iconless.remote`。

## 二、已完成并验证的功能

- 狩猎：真实怪物表、关卡按顺序解锁、出战槽 `squad_slot`（44 填第一个空槽、45 下场）
- 图鉴：只在**首次登记**时弹
- 探险：全局地图链、发现率落地、按 `needDiscoverRate` 三次通关、通关奖励与满星奖励
  **各一次且真的入账**、`is_finish` 表示"这张图打通"、地形决定怪物族群
- **探险事件（2026-10-24）**：1 战斗 / 2 城镇 / 3 温泉 / 4 大餐 / 5 绿洲 /
  6-13 八种灾害；体力、补给、天数、`is_tired`、好运（精英 ×2）全部按客户端字段下发；
  灾害按世界取具体类型，装备 `effectType` 6-13 提供伤害免疫；星级按天数评价。
  详见 `docs/design/explore.md`。
- 租赁：坐骑可拥有多只（最近租的在用）、装备槽位默认 3 上限 9、满员自动替换最旧、
  首次扣费/重复免费、失败写 `RENT_REJECTED`
- 客户端改包（`client/air51-repack/rebuild-client-patches.py` 一键重建）：
  未解锁地图显示锁、BGM 先 stopAll、商店九宫格重排、坐骑热区打开商店、详情页立绘 `removeAll`

## 三、明确未完成

### 1. 坐骑贴图残留 / 闪烁（未定位）

已加 `removeAll()`（`HireMountsUI`、`HireShopInfoUI`），用户反馈仍有。
**下一次必须**：手机连上后，连切两只坐骑，**连续截两张图做像素对比**，判定是
①旧图没清 ②清了但重画导致闪 ③`x/y` 用了未完成加载的 `width` 导致位置跳。
不要再盲改。

### 2. 探险 4 号"大餐"没有文案

客户端 `GameUtil.getExploreEvent` 没有 `case 4`，`ui.txt` 也没有 4 号文案，只能显示宴席
背景。服务端补不了，必须改客户端（`ui.txt` 或 AS3）。

### 3. 灾害对应表 / 数值是 LOCAL DEFAULT

`exploreMap.txt` 只存 6/7 两个灾难槽位，具体是哪一种灾害（6-13）没有表；
`LOCAL_EXPLORE_DISASTERS_BY_WORLD` 是按地区主题与装备备注推断的。资源数值、星级天数
阈值同样是本地设计，全在 `app.py` 顶部 `LOCAL_EXPLORE_*`，按手感可调。

### 4. 替换指定装备

现在是"自动替换最旧"。玩家想要"选择替换哪一件"需要客户端加交互。

### 5. 国王战 109–113 / 公会首领战 93

未实现。拆包契约：
- 国王战 `KingFightInfoUI.as:311+` 要 `att/def{sprite_type,name,img}/index/pic`
- 公会首领 `BossListUI.as:151-156` 要 `refresh_time/boss_ap/max_boss_ap` + 列表

### 6. 世界地图入口

`WorldMapUI` 点击不发请求（详见 `docs/playtest/2026-10-23-evening.md` D-15），
探险只能从世界 1 的地图列表进；世界切换只在请求显式带 `gid` 时生效。

## 四、教训（务必遵守）

1. **不要一次改多件事**。一项：复现 → 读码 → 单改 → 验证 → 提交。
2. **部署前本地起一次服务**。曾因漏常量直接部署导致 104 全部 500。
3. **不要用"看起来合理"的数值替换真实数据**。`equip_count` 写成 9 就让槽位全开。
4. **客户端改包前先确认布局源码**。给 `HireListUI` 重排把九宫格挤到左上角。
5. **`HireListUI.as` 无法用 FFDec 重编译**（原样导入也报 `findproperty`），改不了。
6. **坐骑页只读 `list[0]`**（`HireMountsUI.as:204`），所以服务端必须把在用的排第一。
7. **`is_rented=1` 会隐藏租赁按钮**（`HireShopInfoUI.as:196`），坐骑要按"是否在用"返回。
8. **不要给已有角色自动补东西**：新手坐骑原来每次启动补发，导致"清空坐骑"永远失效。
   新增的默认物品要放在**建角**流程里，不能放在 `_initialize_database`。
9. **诊断脚本的 103 调用会改存档**（扣行动值、加发现率、发经验）。要用真实存档做
   采样时先复制到临时库，别直接打本地服。

## 五、常用命令

```powershell
# 跑测试
cd server; .\.venv\Scripts\python.exe -m pytest tests -q

# 本地服务（后台跑，监听 127.0.0.1:8080）
cd server; .\.venv\Scripts\python.exe -m pet_hunter_server --host 127.0.0.1 --port 8080

# ADB over WiFi（手机和电脑同一局域网）
& F:/SoftWare/adb/adb.exe tcpip 5555
& F:/SoftWare/adb/adb.exe connect 10.89.127.80:5555
& F:/SoftWare/adb/adb.exe -s 10.89.127.80:5555 reverse tcp:8080 tcp:8080
& F:/SoftWare/adb/adb.exe -s 10.89.127.80:5555 reverse --list

# 部署到服务器（用户明确要求时再用；保留远端存档）
$env:VPS_PWD='...'; pwsh -File tools\deploy-remote.ps1 -ServerHost 43.173.99.241 -Port 8080 -SkipApk

# 远端冒烟
cd server; .\.venv\Scripts\python.exe ..\tools\smoke-remote.py --base http://43.173.99.241:8080 --uid local-7b8aa3b620326df390f4e66d

# 重建客户端 APK
cd client\air51-repack; ..\..\server\.venv\Scripts\python.exe rebuild-client-patches.py
# 再用 adt 打包（见 docs/device-runbook.md）
```

## 六、文档索引

- `docs/design/explore.md` —— 探险设计、事件/资源/星级还原与差距
- `docs/design/rental.md` —— 租赁规则与踩坑
- `docs/playtest/2026-10-23-evening.md` —— D-13~D-17 异常记录
- `docs/restore-backlog.md` —— 功能还原清单
- `docs/device-runbook.md` —— 设备检查点与安装记录
- `docs/dev-workflow.md` —— 提交与回滚规矩
