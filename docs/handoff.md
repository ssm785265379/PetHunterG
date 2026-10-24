# 交接文档（当前真实状态）

写于 2026-10-24 中午。目的：换一个干净上下文也能立刻接着干，不用靠回忆。
**只写"已验证的事实"和"明确未完成的项"，不写猜测。**

## 一、部署事实

| 项 | 值 |
|---|---|
| 服务端 | `/opt/pethunter`，systemd `pethunter`，监听 `127.0.0.1:8081` |
| 公网入口 | `http://43.173.99.241:8080/`（nginx 反代，ufw 已放行） |
| 存档 | `/opt/pethunter/instance/game.sqlite3`（部署脚本默认保留，不会被覆盖） |
| 客户端包名 | `air.com.lv1.hunter.iconless.remote` |
| 单测 | **158 passed**（`server/.venv/Scripts/python.exe -m pytest tests -q`） |
| 冒烟 | `tools/smoke-remote.py` 39 条全绿 |

最近可用提交：`9d22397`。工作树只有 `.tmp-serverlog.txt`（未跟踪，忽略即可）。

## 二、已完成并验证的功能

- 狩猎：真实怪物表、关卡按顺序解锁（6 张图，1-6 号瓦片齐全）、出战槽 `squad_slot`（44 填第一个空槽、45 下场、5 只返回真出战）
- 图鉴：只在**首次登记**时弹（6/7 号都已去重）
- 探险：全局地图链（`needExploreMap` 串起 185 张，跨世界）、发现率落地、按 `needDiscoverRate` 三次通关、通关奖励与满星奖励各一次、`is_finish` 表示"这张图打通"、地形决定怪物族群
- 租赁：坐骑可拥有多只（最近租的在用）、装备槽位默认 3 上限 9、满员自动替换最旧、首次扣费/重复免费、失败写 `RENT_REJECTED`
- 客户端改包（`client/air51-repack/rebuild-client-patches.py` 一键重建）：
  未解锁地图显示锁、BGM 先 stopAll、商店九宫格重排、坐骑热区打开商店、详情页立绘 `removeAll`

## 三、明确未完成

### 1. 坐骑贴图残留 / 闪烁（未定位）

已加 `removeAll()`（`HireMountsUI`、`HireShopInfoUI`），用户反馈仍有。
**下一次必须**：手机连上后，连切两只坐骑，**连续截两张图做像素对比**，判定是
①旧图没清 ②清了但重画导致闪 ③`x/y` 用了未完成加载的 `width` 导致位置跳。
不要再盲改。

### 2. 探险体力/补给/天数（代码已写，未部署）

规则已定（本地设计）：每场战斗 −10 体力、休整 +20、灾难 −30、体力上限取
`pet.txt` 的 `energy`、体力为 0 → `is_tired=1`、天数每次 +1。
数值改动只需要改三个常量。

### 3. 槽位解锁方式

命令 106 已实现（免费给满前 9 类，之后按 `LOCAL_EXPLORE_SLOT_PRICE`）。
玩法口径未定：是否消耗道具解锁。

### 4. 替换指定装备

现在是"自动替换最旧"。玩家想要"选择替换哪一件"需要客户端加交互。

### 5. 国王战 109–113 / 公会首领战 93

未实现。拆包契约：
- 国王战 `KingFightInfoUI.as:311+` 要 `att/def{sprite_type,name,img}/index/pic`
- 公会首领 `BossListUI.as:151-156` 要 `refresh_time/boss_ap/max_boss_ap` + 列表

## 四、教训（务必遵守）

1. **不要一次改多件事**。一项：复现 → 读码 → 单改 → 验证 → 提交。
2. **部署前本地起一次服务**。曾因漏常量直接部署导致 104 全部 500。
3. **不要用"看起来合理"的数值替换真实数据**。`equip_count` 写成 9 就让槽位全开。
4. **客户端改包前先确认布局源码**。给 `HireListUI` 重排把九宫格挤到左上角。
5. **`HireListUI.as` 无法用 FFDec 重编译**（原样导入也报 `findproperty`），改不了。
6. **坐骑页只读 `list[0]`**（`HireMountsUI.as:204`），所以服务端必须把在用的排第一。
7. **`is_rented=1` 会隐藏租赁按钮**（`HireShopInfoUI.as:196`），坐骑要按"是否在用"返回。

## 五、常用命令

```powershell
# 跑测试
cd server; .\.venv\Scripts\python.exe -m pytest tests -q

# 部署（保留远端存档）
$env:VPS_PWD='...'; pwsh -File tools\deploy-remote.ps1 -ServerHost 43.173.99.241 -Port 8080 -SkipApk

# 远端冒烟
cd server; .\.venv\Scripts\python.exe ..\tools\smoke-remote.py --base http://43.173.99.241:8080 --uid local-7b8aa3b620326df390f4e66d

# 实时看服务端日志（自动重连）
$env:VPS_PWD='...'; server\.venv\Scripts\python.exe tools\watch-server-log.py --host 43.173.99.241

# 重建客户端 APK
cd client\air51-repack; ..\..\server\.venv\Scripts\python.exe rebuild-client-patches.py
# 再用 adt 打包（见 docs/device-runbook.md）
```

## 六、文档索引

- `docs/design/explore.md` —— 探险设计与实现差距
- `docs/design/rental.md` —— 租赁规则与踩坑
- `docs/playtest/2026-10-23-evening.md` —— D-13~D-17 异常记录
- `docs/restore-backlog.md` —— 功能还原清单
- `docs/dev-workflow.md` —— 提交与回滚规矩
