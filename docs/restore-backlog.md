# 功能还原清单（一次一项）

规则：**一项 = 一次拆包取证 = 一次实现 = 一次验证 = 一次提交**。
不允许把多项混在一个提交里；没取证的不动手。

## 进行中

### R-01 探险：坐骑 / 装备更换

- **拆包依据**：`HireShopUI.as:149` 发 `100{ttype,p,n}`；`:177` 发 `101{gid,ttype}`；
  `HireShopInfoUI.as:248` 发 `102{gid,ttype}`；`HireListUI.as:147` 发 `104{ttype,p,n}`；
  `HireMountsUI.as:163` 发 `{gid,ttype}`。
- **服务端实测**：100 → 101 → 102 → 104 全通，租用后 `104` 的坐骑从 100003 变成 100001
  （坐骑走"删除旧+插入新"的替换语义）。**服务端这一步是好的。**
- **拆包定位到真因（R-01）**：`HireShopUI.initItem()` 用 `_loc1_.width` 算格子坐标，
  但 `PropItem` 在 `initItem` 时**还没数据、宽度为 0** →
  `x = 20 + col*(0+5)`、`y = 90 + row*(0+5)`，**9 个格子全叠在 20~30 / 90~100 这一小块**。
  所以界面看起来"只有一头驴"，装备页同理只有一件，点不到其他条目。
- **修复（改包）**：`HireShopUI.readDatas` 里填完数据后按真实尺寸重排，
  并用 `Math.max(width, 90)` 兜底：
  ```as3
  _cellW = Math.max(_items[_loc11_].width,90) + 5;
  _cellH = Math.max(_items[_loc11_].height,90) + 5;
  _items[_loc11_].x = 20 + _loc11_ % 3 * _cellW;
  _items[_loc11_].y = 90 + (_loc11_ / 3 | 0) * _cellH;
  ```
- **服务端已确认可用**：100 返回 7 只坐骑 / 9 件装备；101 详情、102 租用、
  104 已租（租完 100003→100001 替换成功）。
- **同类隐患**：`ExploreMapListUI.initItem()` 也是同样的写法（地图格子）。
- **状态**：布局已修（真机确认 5 件已租装备 + 4 个锁位正常显示）。

### R-01 追加：坐骑切换在客户端里走不通（已修）
- **拆包证据**：`HireMountsUI.onMouseUpHire` 里 `if(this.data)` 发的是
  `EXPLORE_RENT_KEY(102)` —— 再租一次自己；只有 `data` 为空才发 100 打开商店。
  而服务端总会返回一只坐骑，所以**坐骑商店永远进不去**，无法切换。
  另外那个"按钮"是 `new BitmapData(250,300,true,0)` 的**透明热区**，看不见。
- **修复（改包）**：热区改为**始终**发 `100{ttype:1,p:1,n:9}` 打开坐骑商店。
- **附带修复（服务端）**：`104` 坐骑列表按 `id DESC`，把正在用的那只放 `list[0]`
  （`HireMountsUI.as:204` 只读 `list[0]`），否则界面永远显示第一只（驴）。
- **状态**：APK 已安装，待真机确认。

### R-01 真因（最终定位）：租赁从来没扣过钱，而且账号银币为 0

- `_explore_rent`（102）原实现只 `INSERT OR IGNORE` 一行就回 `ok`，
  **既不校验余额也不扣款**，所以"租"永远成功、永远不花钱，界面上也看不出任何变化。
- 同时玩家账号 `money = 0`，而 `exploreEquip.txt` 里装备租金都记在 `needMoney`（银币），
  所以真正要收费时必然余额不足。
- 已修：按 `needMoney / needPoint / needCrystal` 扣款；余额不足回
  `not_enough + need_*/own_*`（`HireShopInfoUI` 会读这些字段）；
  已拥有的重复租用免费（用于切换）。
- 线上实测：银币 500000 → 499820（扣 180），`is_rented` 变 1，已租装备 6→7 件。

### R-01 遗留：HireListUI 无法改包（已知限制）
- `HireListUI.onMouseUpItem` 对已租道具也发 `102`（重租自己），所以"点了没反应"。
- 第一次尝试改成"打开装备商店"时**把 AS3 写坏了**（FFDec 报
  `Unknown preprocessor instruction: findproperty`），已放弃该次改动。
- 下一步：用更保守的改法（在函数开头直接 `CommandManager.send(100...)` 并 `return`）。

### R-02 探险：体力 / 补给 / 天数

- **拆包依据**：`ExploreUI.as` 读 `energy / cost_energy / add_energy`、
  `supply / cost_supply / add_supply`、`discover_days / add_discover_days`、`is_tired`；
  `ExplorePveUI.as:394-408` 在 `is_tired` 时把音乐换成 `sound_event_200`。
- **现状**：这些字段全部是服务端编的常量（`energy=_pet_energy(...)`，supply 恒 0）。
- **缺口**：配置表**没有任何**体力/补给消耗规则，属于本地设计，需要定数值。
- **下一步**：按"每天掉固定体力、休整回血、灾难掉体力、体力为 0 触发 is_tired"实现。

## 待办（按你给的顺序）

### R-03 图鉴文字居中
- 弹窗 `GetPicItem` 已量过是居中的（面板 536 / 图片 537 / 屏幕 540）。
- 待确认：是不是 `IllustrationTaskUI`（里程碑页，文字硬编码 `x=20/120`）。

### R-04 使用道具过滤
- 需要客户端按 `useType` 过滤：人物界面不显示宠物道具，反之亦然。
- 服务端 22 号拿不到"谁在用"的上下文，只能改包。

### R-05 国王战 109–113
- 拆包：`KingFightInfoUI.as:311+` 需要 `att/def{png_type/name/img}/index/pic` 的立绘描述。

### R-06 公会首领战 93
- 拆包：`BossListUI.as:151-156` 读 `refresh_time / boss_ap / max_boss_ap` + 列表。

### R-07 事件池的完整效果
- 已做：战斗 / 休整（半量发现率）/ 灾难（无进展）。
- 待做：事件与体力/天数联动，灾难是否直接终止行程。

## 已完成（记录用）

- 探险地图链 + 发现率 + 解锁门禁
- 通关奖励一次性 / 满星奖励一次性 / `is_finish` 语义
- 地形决定怪物族群
- 地图角标改为链上序号
- 客户端改包两处：未解锁显示锁、BGM 重叠
