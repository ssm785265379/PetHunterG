# 图鉴与神器协议（25 / 26 / 7 / 48 / 49 / 107 / 108）

本文只记录**客户端代码事实**与**随包配置表**能证明的东西；凡是没有证据的字段/
条目，明确写「未取证」，不用本地猜测填成成功响应。所有数值推导都以
`client/air51-repack/src/data/zh-CN/config/*.txt` 为准。

客户端证据的导出方式（FFDec 26.4.0，只在临时目录，不入库）：

```powershell
& 'D:\Configure\jdk17\bin\java.exe' -jar 'D:\Tool\FFDec-26.4.0\ffdec.jar' `
  -export script $env:TEMP\as3 `
  'client\air51-repack\build\input\APetHunter.swf'

# 神器四个按钮的位图在本地化资源里，不在主 SWF：
& 'D:\Configure\jdk17\bin\java.exe' -jar 'D:\Tool\FFDec-26.4.0\ffdec.jar' `
  -export image $env:TEMP\img `
  'client\air51-repack\build\input\data\zh-CN\res.swf' `
  img_artifact_1 img_artifact_2 img_artifact_3 img_artifact_4
```

## 1. 命令与页面

| showId | CommandManager 常量 | 页面 | 数据来源 |
|---|---|---|---|
| 25 | `PIC_LIST_INFO_KEY` | `IllustrationListUI`（图鉴列表） | `pic.txt` + `pic_unlocked` |
| 26 | `PIC_INFO_KEY` | `IllustrationInfoUI`（图鉴详情） | `pic.txt` |
| 48 | `PICSTEP_INFO_KEY` | `IllustrationTaskUI`（图鉴奖励） | `picStep.txt` + `pic_unlocked` |
| 49 | `PICSTEP_REWARD_KEY` | 同上，领奖 | `pic_step_claimed` |
| 107 | `ACHIEVEMENT_LIST_KEY` | `ArtifactListUI`（神器） | 形状已实现，**条目未取证** |
| 108 | `ACHIEVEMENT_REWARD_KEY` | 神器领奖 | **仍未实现** |

## 2. 25 / 26（图鉴列表与详情）

### 客户端读什么

`IllustrationListUI.as:172-184,208-243`：

- 请求：`send(PIC_LIST_INFO_KEY, {ttype, p, n})`，`n` 固定 9（3×3 格）。
- 响应：`finish_rate`（顶栏「完成度 n%」）+ `pics[]`。
- 每个 `pics[]` 行读 `id` / `icon` / `is_reward`；名称是客户端自己
  `getConfigValue("pic", id, "name")` 解析的，服务端不用给名字。
- `PicItem.as:89-170`：`is_reward`（落到 `data.on`）为 0 时整格画灰并
  `mouseEnabled=false`。所以 **`is_reward` 的语义是「这条图鉴是否已登记」**，
  不是「这条有没有奖励」。
- `ttype` 四个页签由 `IllustrationUI.as:122-145` 发出：
  **1 宠物 / 2 装备 / 3 物品 / 4 发现**。

`IllustrationInfoUI.as:151-225`（26）：只读 `id` / `icon` / `type`，名称和
描述同样由客户端查 `pic.txt`；`icon` 必须是**裸数字**（类里自己做
`getDefinition("p" + icon)`），漏了会被 `catch` 吞掉、页面无图。

### 服务端实现

`app.py` 的 `_pic_catalogue(ttype)` 直接扫 `pic.txt`：

| ttype | `pic.txt type` | 条目数 | 内容 |
|---|---|---|---|
| 1 | 1 | 342 | 宠物 |
| 2 | 2 | 936 | 装备 |
| 3 | 3 | 97 | 物品 |
| 4 | 4 | 42 | 发现（坐骑 + 探险发现物） |
| — | 5 | 54 | 景点/地标（富士山、长城、极光…） |

- 排序用 `sort` 列（跨类型全局 1..1471），保留客户端原本的排列。
- **type 5 没有页签**：`IllustrationUI` 只发 1..4，所以 25 不列这 54 条；
  48 也不计它们（见 §4），避免里程碑进度包含页面上永远看不到的条目。
- `finish_rate = 已登记 / 该页签总数`，有进度时最少显示 1%，未集齐最多 99%，
  全登记才是 100%（342 条里 1 条不能被四舍五入成 0%，也不能在 341/342 时
  提前显示 100%）。
- 分页：`p` 从 1 开始，`n` 被夹在 1..60（客户端发 9）；越界页返回空数组，
  不报错（客户端靠 `pics.length >= n` 判断还能不能翻下一页）。
- 26 接受**任意** `pic.txt` id（以前只认写死的 3 条，其它一律 `-1:506`），
  并补上 `type` 字段。

响应形状：

```json
25  {"finish_rate":5,"pics":[{"index":0,"id":1001,"icon":1001,"is_reward":0}]}
26  {"id":1001,"icon":1001,"type":1,"need_money":0,"is_reward":0,
     "pics":[{"id":1001,"icon":1001,"type":1,"is_reward":0}]}
```

> 25 里 `index` 只是给客户端 `_loc6_[0]` 的兼容字段；`PicItem` 实际不使用它，
> 真正的键是 `id/icon/is_reward`。

## 3. 7（抓宠）与 6（狩猎）的图鉴 id 口径

结论：**现有代码口径一致，但之前是靠数据巧合，现已显式统一到 `pic.txt` id。**

核对方法：

1. `_catchable_pet()` 返回的 `pet_id` 就是 `monster.txt.iconId`，并且要求它
   在 `pet.txt` 里。
2. 对全部 `monster.txt` 行做交叉检查：
   - 1003 个 `iconId` 落在 `pic.txt type=1`；
   - **0 个**落在「只在 `pet.txt`、不在 `pic.txt`」的 63 个 id 上；
   - 那 63 个是 6501+ 的「超级/无双」进化体，野怪不会产出。
3. 所以抓捕时的 `pet_id`、`monster["icon"]`、`pic.txt id` 在可捕捉物种上是
   同一个数；7 号弹窗过滤 `newly` 也就能对上。

改动：

- 新增 `_pic_id_for_pet(pet_id)`：`pet.txt` 有对应 `pic.txt` 行就返回它，
  否则尝试 `pet.txt iconId`，都没有返回 `None`。**它只返回 `pic.txt` 里真实
  存在的 id。**
- 7 号写库改为 `_unlock_pic(c, player_id, [pic_id])`，`_pic_entries()` 也用同
  一个函数解析怪物的 `iconId`。因此「弹窗条目 id == 入库 id == 25 列表 id」。
- 没有 `pic.txt` 行的宠物不写库、不弹「获得图鉴」（客户端
  `GetPicItem.as` 拿不到名字会抛异常）。
- 兼容：旧存档里若已有不在 `pic.txt` 的 `pic_unlocked` 行，**不删除**；25/48
  只统计目录内 id，所以旧行既不会让接口报错，也不会虚增完成度。目前随包数据
  不会产生这种行（上述 63 个进化体不可捕捉）。

## 4. 48 / 49（图鉴里程碑）

`picStep.txt` 是真实的 200 档里程碑：`value` 从 5 到 1000，每档 +5，奖励为
银币/金币/水晶/道具。

- `own_num` 现在 = `pic_unlocked ∩ _pic_book_ids()`，其中
  `_pic_book_ids()` 就是 25 的四个页签（type 1-4，共 1417 条）。
  - 4 个页签合计 1417 > 里程碑上限 1000，整条奖励链可完成。
  - type 5（景点）和旧档 legacy id 不进统计，避免「图鉴数量」和页面总数打架。
- `need_num` 直接来自 `picStep.txt.value`；`is_finish = own_num >= need_num`。
- 页面显示第一个「未领且已达成」的档位，否则第一个未领档位，最后兜底最后一档。
- 49 领奖：写 `pic_step_claimed`，同一档第二次返回 `-1:504`；响应回显本档
  `own_num/need_num/reward_*` 和 `next` 档，供 `IllustrationTaskUI` 整页刷新。

响应形状（新号）：

```json
48  {"id":1,"own_num":0,"need_num":5,"reward_money":0,"reward_point":0,
     "reward_crystal":0,"reward_goods":[{"id":10007,"num":1}],
     "is_finish":0,"value":"ok"}
```

## 5. 107 / 108（神器）

### 客户端事实

- `ArtifactUI.as:79-172`（按钮 79-118，请求 138-172）：铁匠铺 → 神器 页有 **4 个按钮**，分别发
  `107 {ttype:1..4, p:1, n:9}`；按钮位图 `img_artifact_1..4`（`res.swf`）
  上的字分别是 **初级神器 / 中级神器 / 高级神器 / 终级神器**。
- `ArtifactListUI.as:312-420` 只读四个字段（列表渲染在 `showItem()` 279-310）：

  | 字段 | 用途 |
  |---|---|
  | `id` | 存进 `data.id`；点「领取」时作为 108 的 `gid` |
  | `need_money` | >0 时先弹「再次领取神器需要 [金币]」确认框（ui 412） |
  | `is_reward` | 该档已领取过 → 点领取弹 ui 411「你已经领取完该级别的所有神器」 |
  | `pics[]` | 列表条目。每行是 **pic.txt id**；名称/图标由客户端查 `pic` 表（`showItem`），行内 `is_reward` 表示该图鉴已登记 |

- 「领取」按钮逻辑（`ArtifactListUI.as:378-395`）：
  - `!is_reward` 且 `pics` **全部** `is_reward` 为真 → 发 108 `{gid:id}`；
  - `!is_reward` 但有未登记条目 → 弹 ui 410「收集全上面的图鉴，才能领取神器」；
  - `is_reward` 为真 → 弹 ui 411。
- 所以 107 的语义是「某档神器要求的图鉴清单 + 完成度」，不是神器装备列表；
  服务端不返回 `list` 字段（客户端也不读）。

### 服务端实现（形状有证据，条目未取证）

```json
107  {"id":1,"need_money":0,"is_reward":0,"pics":[]}
```

- `ttype` 必须是 1..4；`p/n` 只为协议兼容接收（列表翻页在客户端
  `showItem()` 里做，不再请求服务端），非法值返回 `-1:100`，uid 不存在
  `-1:103`。
- `id = ttype`：它是唯一稳定的「档位」标识，用于 108 的 `gid`。
- `need_money = 0`：首次领取免费；「再次领取」的金额随包数据里没有。
- `is_reward = 0`：108 未实现，没有任何档位可以被领过。
- `pics = []`：**未取证**，见下。

### 未取证：每档到底要哪些图鉴

随包配置里没有「神器档位 → 图鉴 id 列表」的表，已排查：

- `pic.txt`：只有 `type`（图鉴页签）和 `sort`，没有档位/神器字段；
  其中 72 条神器装备的图鉴（57001-57056 / 67001-67056）用 `remark` 标了
  「初级/中级/高级/终级神器」，但这只能说明它们是**神器装备的图鉴**，不能
  证明它们就是某一档的领取条件（领取条件若等于奖励本身会形成循环）。
- `equip.txt`：72 条神器装备（6 套 × 普通/超级两档 × 3 部位 × 2 性别），
  `properties` 1-6、`remark` 初/中/高/终级；没有「需要图鉴」列。
- `task.txt` / `picStep.txt` / `exploreMap.txt` / `help.txt` / `dialog.txt`：
  没有档位到图鉴的映射。`dialog.txt 13` 只说「完成所有的狩猎和探险地图，就能
  获得激活神器所需要的图鉴」，是玩法描述，不是 id 清单。
- `ArtifactListUI` 自己不筛选、不推导条目，完全信任服务端 `pics`。

因此 `pics: []` 是**有意保持的空结构**：返回真实但错误的条目会让玩家在错误
条件下看到「可领取」（108 一旦实现就会发错奖励）。等拿到原服响应样本或补齐
映射表后，只需在 `_achievement_list` 里按 `ttype` 填 `pics`，形状不用再改。

### 108 状态

**未实现，也不伪造，而且显式拒绝。**

注意 `ArtifactListUI.as:380` 的边界：`pics` 为空时
`_loc5_ >= _loc4_` 是 `0 >= 0`，客户端会**认为已集齐**并把「领取」按钮接到
108。如果 108 不注册，请求会落到路由表的通用兜底 `{"value":"ok"}`，看起来
像领取成功（实际没发任何东西）。所以 108 注册为 `_artifact_reward`，固定回
`-1:100`（非法操作），并且：

- 不扣钱、不发道具/装备（测试逐项断言）；
- 响应不是成功信封，客户端弹错误而不是假奖励。

实现 108 需要：

1. 每档的图鉴清单（上节）；
2. 每档发放的神器 id/数量（`equip.txt` 的 57001-57056 / 67001-67056 是候选，
   但「哪一档发哪些」同样未取证）；
3. 「再次领取」的金币费用（107 的 `need_money`）。

拿到这些证据后，把 107 的 `pics` 填上、`_artifact_reward` 改成一次性领取
（写领取档位、扣费、发奖）即可，客户端不用改。

## 6. 验证

```powershell
cd F:\git\PetHunterG\.worktrees\b14\server
F:\git\PetHunterG\server\.venv\Scripts\python.exe -m pytest tests -q
F:\git\PetHunterG\server\.venv\Scripts\python.exe -m pytest tests\test_illustration.py -q
```

新增用例覆盖：

- 25 四个页签的条目数（342/936/97/42）、`n=9` 真分页与末页余数；
- `finish_rate` 随 `pic_unlocked` 变化、`is_reward` 跟随解锁；
- 7 号抓捕后 25 的解锁态、48 的 `own_num` 三处同一 id；
- 48 只统计 25 目录内 id（legacy/type5 行保留但不计数）、49 防重复；
- 107 四档形状、空 `pics`、非法 `ttype`/分页参数与未知 uid。

桌面还需要人眼确认（agent 不代点）：

1. 集市 → 图鉴 → 宠物/装备/物品/发现：四个页签都有格子、翻页内容变化、
   顶栏「完成度」不再恒 0；
2. 捕捉一只新宠物：弹窗只出现新条目，进图鉴后该格不再是灰的；
3. 铁匠铺 → 神器 → 初/中/高/终级：页面不再整屏空白，能渲染「领取神器图鉴
   完成度 0/0」；点「领取」应收到服务端 `-1:100` 并弹错误提示（不是无响应、
   也不是假的成功奖励）。
