# 交接文档（当前真实状态）

写于 2026-10-24 晚。目的：换一个干净上下文也能立刻接着干，不用靠回忆。
**只写"已验证的事实"和"明确未完成的项"，不写猜测。**

> **2026-10-25 的最新快照见 [`docs/handoff-2026-10-25.md`](handoff-2026-10-25.md)**：
> 阶段1（道具场景过滤 + 养成流程）、道具使用弹窗、错误协议补 tab、限时增益道具、
> 扩建证书、开蛋弹宠物、客户端弹窗排版，以及构建命令与踩坑记录。
>
> 2026-10-25 下午这一轮（提交 `9a93a16`）的核心结论，先看这三条：
> 1. **业务错误以前全被客户端吞掉**：服务端回裸 `-1:300`（没有 tab），客户端按 tab 切分后
>    数据段是 `"null"`，`GameUtil.isError()` 失效 → 必须回 `-1\t-1:<id>`。
> 2. **真机上 `Shape`/裸 `Bitmap` 收不到 `mouseUp`**：遮罩看着在、点击会穿透。所有可点区域
>    一律用 `cc.lv1.game.item.Button` 包一层。
> 3. **开蛋/开箱结果**走 `players.pending_box` → 22 号 `notice_box`，因为 50 的响应不保证
>    路由回背包页。


## 一、当前部署 / 联调方式

用户要求：**先在本地 WiFi 联调，不推服务器**，等他通知再回到远端。手机上有两个包：

| 项 | 值 |
|---|---|
| 本地服务 | `server/.venv/Scripts/python.exe -m pet_hunter_server --host 127.0.0.1 --port 8080` |
| 本机 WiFi | `10.89.127.154` |
| 手机 WiFi | `10.89.127.80`，ADB `10.89.127.80:5555`（`adb tcpip 5555` + `adb connect`） |
| 端口转发 | `adb -s 10.89.127.80:5555 reverse tcp:8080 tcp:8080` |
| 本地联调包（当前） | `air.com.lv1.hunter.localwifi`，SWF 内 4 个 URL = `http://127.0.0.1:8080` |
| 该 APK SHA-256 | `35756A6ECE86E36F23FA1D391200A1E12956C1391A04C63FC33DBF59A4A2470E`（`build/out/PetHunterG-LocalWiFi.apk`，含 22 号 target + 使用弹窗 + 素材可点 + 开蛋宠物弹窗） |
| 该 SWF SHA-256 | `248819ECE137314A375291ECEBF1BE285D849EACC71C7D64F28B246C373CB297`（`build/input-localwifi/APetHunter.swf`） |
| 新包签名 | `build/localwifi.p12`，密码在 `build/localwifi-signing.txt`（都在忽略的 build/ 里）；证书 SHA-256 `7090d1010bd965904b418598d82434c994eaaa7b39114a10aebd9a0bbb3e96ee` |
| 旧包（保留） | `air.com.lv1.hunter.iconless.localusb`：签名密码是当时随机生成、**未保存**，无法覆盖升级，所以新包旁装；旧会话仍在旧包里 |
| 存档 | `server/instance/game.sqlite3`（本地，未上传） |
| 单测 | **175 passed**（`server/.venv/Scripts/python.exe -m pytest tests -q`） |
| 手机状态（2026-10-25 13:20） | **USB 掉线**（`adb devices` 空）。连回后先 `adb reverse tcp:8080 tcp:8080`，否则客户端弹「网络错误」 |

> 2026-10-25：手机当前走 USB（serial `24086b59`），WiFi `10.89.127.80:5555` 当时连不上；
> 两种连接都要 `adb reverse tcp:8080 tcp:8080`。
> 本地服务是否在跑用 `Get-NetTCPConnection -LocalPort 8080 -State Listen` 确认；
> 它**没有 reloader**，改完服务端必须重启。

新包要**重新登录**：账号 `ssm7852`（存档在服务器上，不变）。

远端旧部署（**本轮未动**）：`/opt/pethunter`，systemd `pethunter`，`127.0.0.1:8081`，
nginx `http://43.173.99.241:8080/`，客户端 `air.com.lv1.hunter.iconless.remote`。

## 二、已完成并验证的功能

- **道具弹窗 / 错误提示 / 开蛋宠物（2026-10-25 下午，提交 `9a93a16`，175 passed）**：
  - **错误协议**：`_pet_error` 与 17 处硬编码错误体统一改成 `-1\t-1:<id>`。裸 `-1:300`
    会被客户端当成数据 `"null"` 吞掉（`APetHunter.as:143-147` 先按 tab 切分），
    以前"道具没扣也没提示"就是这个原因。真机验证：体力满用体力饮料弹
    「现在体力充沛，不需要使用」。
  - **错误码**：7/26 满值 → 415；prop.txt 有行但无效果（宠物名片/奇异口袋/扩建证书）→ 417
    「该道具不能直接使用」；开蛋宠物满 → 500「宠物数量已达最大」。
  - **限时增益**：新表 `player_buffs(player_id, kind, value, expire_at)`，
    kind = prop.txt 的 type。10026 幸运四叶草（全能力 +30 进 `_battle_side`，6/24/74 都生效）、
    10027 狩猎秘籍（狩猎经验 ×1.5，value=1.5 需要 `ratio`）、10006 荣誉勋章（记录擂台水晶 ×2，
    本地擂台仍不给水晶）、三者按"狩猎行动值上限 +5/个"累加 `players.max_ht_ap`；
    10504 探险饮料回 `explore_ap`。真机：四个道具都会扣数量并弹结果。
  - **宠物栏扩建**：11 号 `own_card_num` 报背包真实 10013 数量，40 号真扣 1 个，
    不够回 205。以前写死 1 且不扣道具（免费无限扩建）。
  - **开蛋/开箱**：50 号把开出的宠物写 `players.pending_box`（JSON 数组，含 `pets.id`），
    22 号 `notice_box` 带回并清空。客户端「获得宠物 ×N」：3 列、两行可视、超出上下拖动
    （`scrollRect`）、点宠物发 12 号进面板且**不移除**、右上角小 X 或点空白关闭。
  - **客户端弹窗**：数量行按真实按钮宽度居中（`−`/`+` 与数字间 120）；数字可点输入
    （`Text.input` + 自建 `TextFormat`）；`√/X` 竖向补 8px（`img_cancel` 美术偏下 6.5px）；
    素材可点并提示 417；遮罩/面板改 `Button`。

- **道具场景过滤 + 养成流程（2026-10-25 凌晨，阶段1）**：
  - 22 号请求现在带 `target`（人物/家园 0、宠物 index），服务端在分页前按 `use_type`
    过滤：人物只回 0/1，宠物只回 2；旧客户端不带 `target` 保持全量。
  - 训练中的宠物（`train_end > now`）不再出现在 505 选宠、42/5 出战列表、6/24/74/103
    战斗与 506 对手展示里；44 直接拒绝；开始训练自动 `squad_slot=0`。
  - 训练收益 `train_gain`/`train_gain2` 两列分别记账，504 结算分别加到两列，接近 1000
    上限时不会把第二列算多。
  - 真机验证：人物背包 81 格全是人物/通用道具（无宠物饼干等），宠物背包 80 格全是
    宠物道具（无星星宝箱/扩建证书等）；烈焰龙开始训练后出现在养成槽位倒计时，
    再打开选宠页时它已消失。170 passed。
  - 设计/计划：`docs/superpowers/specs/2026-10-24-...`、`docs/superpowers/plans/2026-10-24-bag-context-and-training.md`

- 狩猎：真实怪物表、关卡按顺序解锁、出战槽 `squad_slot`（44 填第一个空槽、45 下场）
- 图鉴：只在**首次登记**时弹
- 探险：全局地图链、发现率落地、按 `needDiscoverRate` 三次通关、通关奖励与满星奖励
  **各一次且真的入账**、`is_finish` 表示"这张图打通"、地形决定怪物族群
- **探险事件（2026-10-24）**：1 战斗 / 2 城镇 / 3 温泉 / 4 大餐 / 5 绿洲 /
  6-13 八种灾害；体力、补给、天数、`is_tired`、好运（精英 ×2）全部按客户端字段下发；
  灾害按世界取具体类型，装备 `effectType` 6-13 提供伤害免疫；星级按天数评价。
  详见 `docs/design/explore.md`。
- **关卡门禁（2026-10-24 晚）**：前置图通关才解锁下一张；5 星完美通关把本关
  `is_perfect=1` 关闭（客户端锁住，99/103 都拒绝）；4 星不关闭、可回去补星；
  98 列表从当前关往前留 4 张，并下发 `best_star`/`is_perfect`/`is_cleared`。
- **后半程怪物（2026-10-24 晚）**：物种按全局链位置从 monster.txt 选（不再写死波利），
  出场等级统一用 `reference_lv`（队伍 +15 橡皮筋），同图按进度轮换对手。
- **BGM**：`ExploreMapListUI` 换世界/翻页前 `stopAll()`（旧 localusb 包没有这个补丁，
  所以之前会叠加；新 localwifi 包已带）。
- 租赁：坐骑可拥有多只（最近租的在用）、装备槽位默认 3 上限 9、满员自动替换最旧、
  首次扣费/重复免费、失败写 `RENT_REJECTED`
- 客户端改包（`client/air51-repack/rebuild-client-patches.py` 一键重建）：
  未解锁地图显示锁、BGM 先 stopAll、商店九宫格重排、坐骑热区打开商店、详情页立绘 `removeAll`

## 三、明确未完成

### 0. 宠物奖励弹窗"点空白关闭"未复验（手机 2026-10-25 13:20 掉线）

最后一版把遮罩/面板从 `Shape`/裸 `Bitmap` 换成 `Button`，并加了右上角小 X。
**下一次手机连上后**：开多个蛋 → ①点空白处 ②点右上角小 X，确认能关且点击不再穿透到背包格子。
若仍关不掉，直接改成面板底部一个显式「关闭」按钮（`img_cancel`）——不要再猜事件模型。

顺带确认：一次开 2 个以上蛋时，弹窗是否列出多只、拖动是否顺、点宠物进面板后返回弹窗是否还在。

### 0b. 荣誉勋章的水晶加成没有收益点

`_arena_battle` 的 `reward_crystal` 仍是 0，所以 10006 只落地了"记录 buff + 行动值上限 +5"。
等阶段 3 做擂台经济时一起给基础水晶奖励，再乘 `_player_buffs(...)[6]`。

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
10. **签名密码必须落到本地文件**：localusb 的 p12 密码是 `[Guid]::NewGuid()` 现生成、
    没有保存，结果无法同包覆盖升级，只能新包名旁装 + 重新登录。新包已写
    `build/localwifi-signing.txt`（build/ 被忽略，不会进 Git）。
11. **不要写死"基础怪"**：探险曾把 monster 1 写进每一张图，后半程全是一只 lv1 波利。
    需要变化的内容要按关卡/地形/进度取值。
12. **错误响应必须带 tab**：`-1\t-1:<id>`。裸 `-1:<id>` 会被客户端切成数据 `"null"`，
    `isError()` 失效、错误静默消失。改这个格式会动到 ~59 处测试断言。
13. **真机上 `Shape` / 裸 `Bitmap` 收不到 `mouseUp`**（AIR 51 + `renderMode=direct`）：
    遮罩看着在，点击穿透到背后。可点区域一律 `new Button(bitmap)`（`cc.lv1.game.item.Button`）。
14. **`private static function` 里不能引用实例方法**：宠物弹窗第一版把建图标的工厂写成 static，
    里面 `addEventListener(..., onPetRewardPick)` 指向实例方法 → 真机构造时抛错，连结果提示都不弹。
15. **FFDec `-importScript` 不覆盖已存在的输出文件**，失败时 exit code 还可能为 0：
    重建前先删 `build/input-explore/step-*.swf`，并检查 `stat().st_size` 有没有变。
16. **`Text` 输入框要自己设 `defaultTextFormat`**：`type="text_area_center"` 只改内部 `_tf.align`，
    不赋值 `defaultTextFormat`；顺序是 `size/bold/color` → `defaultTextFormat` → `input=true` → `text`。
17. **`client/` 下写文件被拒（Access denied）不是代码问题**：是 Windows 文件权限/沙箱授权
    没铺到子目录。本次用 DSH 的 `diagnose-windows-sandbox-acl` 脚本修过一次
    （只给当前用户补一条完全控制项，备份与回滚命令在 `_acl-recovery/`，未入库）。

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
