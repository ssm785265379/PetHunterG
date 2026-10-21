# 宠物猎人 — 服务端响应契约（13 个命令）

> 只读分析产物，未修改任何反编译文件。
> 基准路径：`scripts/cc/lv1/game/`，下称 `…/game/`
> HTTP 端点：`GameUtil.url + "flash.do"`（`GameUtil.as:29`，默认 `http://192.168.0.102:8080/`）
> 请求体：`m=show&showId=<cmd>`（`CommandManager.as:312`、`:388`），POST。

---

## 0. 线协议（先读这个，否则字段名会全错）

`APetHunter.as:133-163` 是唯一的响应解析入口：

```
响应 body（纯文本，非 JSON 包裹）
  → GameUtil.filter()          去掉末尾 \t      (GameUtil.as:644)
  → split("\t")                GameUtil.separated = "\t"   (GameUtil.as:47)
  → shift()  #0  = cmd:int     路由用的命令号（可与请求 cmd 不同！）
  → shift()  #1  = payload     JSON.parse(payload)   (APetHunter.as:161)
  → Navigator.con.readDatas(cmd, parsed)
```

关键结论：

| 事实 | 依据 | 对服务端的影响 |
|---|---|---|
| 第 1 段是**响应 cmd**，不是 HTTP 状态 | `APetHunter.as:143-145` | 必须回 `<cmd>\t<json>`，不能只回 JSON |
| 第 2 段是 `JSON.parse` 的结果 | `APetHunter.as:161` | 必须是**对象**或**数组**字面量；纯数字会被 parse 成 int，`param2.xxx` 得 undefined |
| 错误码走另一条路：`-1:<id>` 正则 | `GameUtil.isError` `GameUtil.as:300-317` | 第 2 段若匹配 `/-1\:([\-0-9]+)/` 就弹 `error.txt[id]`，**不进入 readDatas**。id=106 额外弹窗后跳回 LOGIN（`APetHunter.as:150-153`） |
| HTTP 501 → `ioError` | `HttpRequest.as:74-79` + `APetHunter.as:166-169` | 弹 `error.txt[0]`「网络错误」并 `flow(LOGIN)`。这正是你观察到的现象 |
| **路由只看第 1 段**，与请求 cmd 无关 | `APetHunter.as:162` | 服务端可自由改写回包 cmd 来跳页，例如 82 由 507 触发但回 `82` |
| 顶层分发 | `MainUI.as:74-319` | 未列在 `MainUI.readDatas` switch 里的命令走 `default:` → 直接喂给**当前页** `Navigator.item.readDatas()`（`MainUI.as:317-318`） |

配置表加载于 `LoadingUI.as:283-343`，注册名见 `LoadingUI.as:413-488`：
`error, ui, skin, nature, help, dialog, task, prop, pet, exploreMap, upRole, pic, skill, picStep, equipEnchant, monster, exploreEquip, worldMap, equip`
全部按 `\t` 切分，首行是列名（`Config.as:122-128`），`getConfigValue(table, id, column)` 取列（`GameUtil.as:319-336`，缺表/缺行/缺列**一律返回空串，不抛异常**）。

---

## 1. `24 ARENA_KEY` — 竞技场战斗结算

### 1.1 发送点

| 位置 | 参数 |
|---|---|
| `ui/RingUI.as:243` | 无参 |
| `item/FightResultItem.as:885` | 无参（结算页「继续挑战」） |

### 1.2 消费点

- `MainUI.as:128-131` → `flow(FIGHT_RING_RESULT)` → `Navigator.as:432-434` 构造 `RingResultUI`
- `ui/RingResultUI.as:264` `readDatas(ARENA_KEY, …)` — 主逻辑
- `item/FightResultItem.as:339-419` — 结算面板，由 `RingResultUI.as:210-212` 以 `ARENA_KEY` 二次调用

### 1.3 响应字段穷尽清单

**顶层**

| 字段 | 判空 | 语义 / 取值 | 来源 |
|---|---|---|---|
| `is_win` | 无保护，`FightResultItem.as:142` 直接 `!param2.is_win` | bool，决定 img_win / img_lose | — |
| `att_list` | 有保护 `RingResultUI.as:283` | Array，玩家方，索引 0=角色 1/2=宠物 | — |
| `def_list` | 有保护 `RingResultUI.as:317` | Array，敌方玩家 | — |
| `record` | 有保护 `RingResultUI.as:356` | Array，回放帧序列 | — |
| `arena_ap` | **无保护** `FightResultItem.as:349` 直接字符串拼接 | int，竞技场积分 | — |
| `max_arena_ap` | **无保护** 同上 | int，积分上限 | — |
| `arena_rank` | 有保护 `FightResultItem.as:369` | int 名次，0/null 时不显示 NO. 图标 | — |
| `rage_point` | **无保护** `FightResultItem.as:405` `int(param2.rage_point)` | 0..100，`==100` 时宝箱可点（`BboxItem1.as:36-48`），否则灰化不可点 | — |
| `reward_point` | 有保护 `>0` `:381` | int 银两奖励 | — |
| `reward_crystal` | 有保护 `>0` `:392` | int 水晶奖励 | — |

**`att_list[i]`**（`RingResultUI.as:288-315`）

| 字段 | 判空 | 语义 |
|---|---|---|
| `img` | **无保护**，`RingResultUI.as:290` `_loc17_.items = _loc11_.img` → `ShowItem.items` `ShowItem.as:41` `param1.split("_")`，null 直接 NPE | **String**，造型码串，**下划线分隔的多段**，每段查 `skin.txt` 取 `z` 排序，加载为 `s<id>` 影片 |
| `name` | 三元保护 `:299` | String；`is_pet` 为真且 `name` 空时回落 `pet.txt[id].name` |
| `is_pet` | 直接读 `:299` | bool，false=角色，true=宠物 |
| `id` | 直接读 `:299` | int，`pet.txt` 主键 |
| `pre_lv` | 直接读 `:302` | int，**战前等级**（BoxItem1 显示 "lv " + level） |
| `hp` | 直接读 `:303` | int，**同时用作初始 hp 与 maxhp**（`:303-304`），血条满 |
| `lv` | `:235` 之后才用 | int，战斗后等级；`lv > pre_lv` 时显示升级箭头（`BoxItem1.as:142-148`） |

**`def_list[i]`**（`RingResultUI.as:322-354`）

| 字段 | 判空 | 语义 |
|---|---|---|
| `img` | **无保护** `:342` `_loc8_.data = {"skin":_loc11_.img}` → `Pet.as:121` `getDefinition("p"+skin)`，null → `new null()` NPE | String，`p<img>` 单造型（非下划线串） |
| `name` | 三元保护 `:333` | 同上，回落 `pet.txt` |
| `is_pet` | 直接读 `:333` | bool |
| `id` | 直接读 `:333` | int |
| `lv` | 直接读 `:336` | int 等级 |
| `hp` | 直接读 `:337` | int，初始=最大 |

**`record[i]`**（`RingResultUI.as:364-509`）

| 字段 | 判空 | 语义 |
|---|---|---|
| `att` | 有保护 `if(_loc11_.att)` `:369` | Object，本回合主动方 |
| `att.team` | 直接读 `:371` | int，**1=玩家方 → `_p1`/`_box1`；其他=敌方 → `_p2`/`_box2`** |
| `att.code` | 直接读 `:382` | int，**槽位下标 0..2**，用于索引 `_p1`/`_box1`。>2 会得到 undefined，`FightProcess.as:137-138` 随后 NPE |
| `att.skill` | 有保护 `:389` | Object 主技能 |
| `att.skill.id` | → `skill.txt[id].name` `:393` | int |
| `att.skill.pro` | `:394` | int 五行（`GameUtil.getFive` 0/1/2/3/4/5/6/50/51/99/100，`GameUtil.as:388-417`） |
| `att.skill.dm` | `:395` | int 伤害 → `_loc24_.value` |
| `att.ext_skill` | 有保护 `:398` | Array 附加技能 |
| `att.ext_skill[].id/type/dm/lv` | 逐项判空 `:406` | id→`skill.txt.name`；type 是效果类型码；dm→value；lv→level；`t=1`（攻方） |
| `att.buffs` | 有保护 `:419` | Array 增益 |
| `att.buffs[].id/type/dm/lv/effect_turn` | 逐项判空 `:426` | 同上 + `effect_turn`，`==0` 时立即结算（`FightProcess.as:943,957`） |
| `def` | 有保护 `:442` | Object，被动方（同 att 结构） |
| `def.team/code` | `:444,455` | 同 att |
| `def.skill` | **未读取** | `def` 分支只读 `ext_skill`/`buffs`，`skill` 被忽略 |
| `def.ext_skill[].id/type/dm/lv` | 逐项判空 `:472` | `t=2`（守方） |
| `def.buffs[].id/type/dm/lv/effect_turn` | 逐项判空 `:492` | `t=2` |

`type` 取值域由 `FightProcess.getSkillEffect(n)` 反推（`FightProcess.as:139,159,247,317,943…`）：
`1`=治疗(正数加血) `2`=持续伤害(负数扣血) `4`=主技能命中 `7`=闪避相关 `18`=持续状态。
`skill.value` 符号即治疗(+) / 伤害(−)（`FightProcess.as:196-201,586-591`）。

### 1.4 最小可用 JSON 骨架

```json
{"is_win":true,
 "arena_ap":10,"max_arena_ap":20,"arena_rank":3,"rage_point":0,
 "reward_point":100,"reward_crystal":5,
 "att_list":[{"img":"1001","name":"","is_pet":false,"id":0,"pre_lv":10,"lv":10,"hp":500},
             {"img":"2001_2002","name":"","is_pet":true,"id":2001,"pre_lv":10,"lv":10,"hp":300},
             {"img":"2003_2004","name":"","is_pet":true,"id":2003,"pre_lv":10,"lv":10,"hp":300}],
 "def_list":[{"img":"3001","name":"对手","is_pet":false,"id":0,"lv":10,"hp":480},
             {"img":"4001","name":"","is_pet":true,"id":4001,"lv":10,"hp":250},
             {"img":"4003","name":"","is_pet":true,"id":4003,"lv":10,"hp":250}],
 "record":[{"att":{"team":1,"code":0,
            "skill":{"id":1001,"pro":1,"dm":120},
            "ext_skill":[{"id":2001,"type":1,"dm":80,"lv":3}],
            "buffs":[{"id":3001,"type":2,"dm":-15,"lv":2,"effect_turn":3}]}}]}
```

---

## 2. `73 COPY_LIST_KEY` — 副本（深渊）关卡列表

### 2.1 发送点

| 位置 | 参数 |
|---|---|
| `ui/FightUI.as:141-144` | `p`=1, `n`=9 |
| `ui/AbyssMapUI.as:162-165` `send()` | `p`=`_page`, `n`=`_item_num`=9 |

### 2.2 消费点

`MainUI.as:152-155` → `flow(FIGHT_ABYSS)` → `Navigator.as:438-440` `AbyssMapUI` → `ui/AbyssMapUI.as:181` `readDatas`

### 2.3 响应字段穷尽清单

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `cd` | 有保护 `:186` `param2.cd && !=0` | int 毫秒剩余 CD；客户端本地倒数，归零清空文本。**必须 >0 才显示** | — |
| `maps` | **无保护** `:197-199` `int(_loc5_.length)`，`_loc5_` 为 null → NPE | Array，`_page_num = maps.length`（**注意：等于本页返回条数，不是总页数**；翻页条件是 `_page_num >= _item_num`，即满页才允许下一页） | — |

**`maps[i]`**（`AbyssMapUI.as:204-214` → `MapItem.updata()` `MapItem.as:299-331`）

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `code` | 直接读 `:208` | int，显示为右上角关卡序号（`MapItem.as:201-214`），>0 才显示 | — |
| `id` | 直接读 `:209` + `:173` | int，回传为 74 的 `hid` | — |
| `is_battle_able` | 直接读 `:211` | bool → `isClick`；**false 会把该格子锁上**（`MapItem.as:315` `lock = data.isClick ? false : true`），锁定后点击只播动画不发请求 | — |
| `finish_rate` | 直接读 `:212` → `perctnt1` | int 0..100 完成率 | — |
| `finished_num` | 直接读 `:213` → `pass` | int 通关次数；`perctnt1==100` 时显示为通关数字，否则隐藏改显 `ui.txt[79]`（`MapItem.as:238-260`） | — |

图标的 `icon_map_1000` 是**硬编码**在 `AbyssMapUI.as:210`，不从配置表来。锁的判定还额外看 `data.pass != null || data.perctnt != null || data.star != null`（`MapItem.as:303`）——但这三个键 AbyssMapUI 从不设置，所以 `_percentBack` 不可见，这是正常的。

### 2.4 最小可用 JSON 骨架

```json
{"cd":0,
 "maps":[{"code":1,"id":1001,"is_battle_able":true,"finish_rate":100,"finished_num":3},
         {"code":2,"id":1002,"is_battle_able":true,"finish_rate":50,"finished_num":1},
         {"code":3,"id":1003,"is_battle_able":false,"finish_rate":0,"finished_num":0}]}
```

---

## 3. `74 COPY_BATTLE_KEY` — 副本战斗结算

### 3.1 发送点

`ui/AbyssMapUI.as:173` — `{"hid": <maps[i].id>}`

### 3.2 消费点

`MainUI.as:156-159` → `flow(FIGHT_ABYSS_RESULT)` → `Navigator.as:441-443` `AbyssResultUI`
- `ui/AbyssResultUI.as:253` `readDatas`（**注意无 `if(param1==…)` 守卫，任何落到该页的包都会被当副本战斗处理**）
- `item/FightResultItem.as:420-495` — 由 `AbyssResultUI.as:204-206` 以 `COPY_BATTLE_KEY` 二次调用

### 3.3 与 HunterResultUI 契约对比 —— **可以完全复用**

我逐字段比对了 `AbyssResultUI.readDatas`（`:297-534`）与 `HunterResultUI.readDatas`（`:297-…`，`ui/HunterResultUI.as:340+`）以及 `AbyssResultUI` 与 `RingResultUI`：

| 维度 | RingResultUI(24) | AbyssResultUI(74) | HunterResultUI(6) | 结论 |
|---|---|---|---|---|
| `is_win` | `:271` | `:285` | `:305` | 一致 |
| `att_list[].img/name/is_pet/id/pre_lv/lv/hp` | `:299-306` | `:313-320` | `:363` | **完全一致** |
| `def_list[].img/name/is_pet/id/lv/hp` | `:333-342` | `:347-357` | `:398` | 一致 |
| `record[].att/def` + `team/code/skill{id,pro,dm}/ext_skill{id,type,dm,lv}/buffs{…,effect_turn}` | `:369-507` | `:383-521` | `:445+` | **逐字段一致** |
| `skill` 名映射 | `skill.txt[id].name` `:393` | `:407` | `:458` | 一致 |

**唯一差异**（不影响复用）：

1. `def_list` 名字回落的配置表不同 —— 24 用 `pet.txt`（`RingResultUI.as:333`），74 用 **`monster.txt`**（`AbyssResultUI.as:347`）。发包时 `def_list[].name` 一律填非空字符串即可绕过。
2. 74 多了宠物升级显示（`AbyssResultUI.as:227-245`，读 `att_list[].lv` 与 `.pre_lv` 比对）+ `pic` 字段（`:246-249` `GameUtil.getPic`）。
3. 74 少了 `arena_ap` / `arena_rank` / `rage_point`；`FightResultItem.as:420-495` 只读 `is_win / reward_point / reward_crystal / reward_goods`。

### 3.4 响应字段穷尽清单（仅列与 24 不同 / 追加的）

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `is_win` | 无保护 `:285` | bool | — |
| `att_list` / `def_list` / `record` | 同 24 | 同 24 | 同 24 |
| `reward_point` | 有保护 `>0` `FightResultItem.as:442` | int 银两 | — |
| `reward_crystal` | 有保护 `>0` `:453` | int 水晶 | — |
| `reward_goods` | 有保护 `if(param2.reward_goods)` `:464` | Array，逐项判空 `:472` | — |
| `reward_goods[].id` | 直接读 `:476` | int → **`pic.txt[id].iconId`** | `pic.txt` |
| `reward_goods[].num` | 直接读 `:477` | int 数量 | — |
| `pic` | 有保护 `:246` | Array，插画获得弹窗；每项见 §9.4 | `pic.txt` |

### 3.5 最小可用 JSON 骨架

```json
{"is_win":true,
 "reward_point":200,"reward_crystal":10,
 "reward_goods":[{"id":10006,"num":1}],
 "att_list":[{"img":"1001","name":"","is_pet":false,"id":0,"pre_lv":10,"lv":11,"hp":500},
             {"img":"2001_2002","name":"","is_pet":true,"id":2001,"pre_lv":10,"lv":10,"hp":300},
             {"img":"2003_2004","name":"","is_pet":true,"id":2003,"pre_lv":10,"lv":10,"hp":300}],
 "def_list":[{"img":"5001","name":"哥布林","is_pet":true,"id":5001,"lv":12,"hp":400},
             {"img":"5003","name":"哥布林兵","is_pet":true,"id":5003,"lv":12,"hp":350}],
 "record":[{"att":{"team":1,"code":0,"skill":{"id":1001,"pro":1,"dm":200},
            "buffs":[{"id":3001,"type":2,"dm":-20,"lv":2,"effect_turn":2}]},
            "def":{"team":2,"code":0,"ext_skill":[{"id":5001,"type":2,"dm":-30,"lv":1}]}}]}
```

---

## 4. `507 REQUEST_ARENA_RANK_KEY` — 竞技场排行榜

### 4.1 发送点

`ui/RingTopUI.as:170-173` `send()` — `{"p":_page, "n":_item_num}`，`_item_num = 8`（`:85`）。构造函数即调 `send()`（`:50`）。

### 4.2 消费点

`RingTopUI` **不在 `MainUI.readDatas` switch 中** → 走 `MainUI.as:317-318` `default:`，直接投给当前页 `Navigator.item.readDatas()`。
`ui/RingTopUI.as:206` `readDatas`

### 4.3 响应字段穷尽清单

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `refresh_time` | **无保护** `:212` `GameUtil.getTime(param2.refresh_time)` 传 int 给 `param1:int` → undefined 强转 = 0 → 显示 "00:00:00"，同时 `:211` 存进 `this.data` 驱动本地倒数 | int **毫秒**（`GameUtil.getTime` 内部 `param1/1000`，`GameUtil.as:246`） | — |
| `arena_rank` | **无保护** `:215` 字符串拼接 | int 我的名次；null → 文本 "我的排名:null" | — |
| `ranks` | **无保护** `:216-217` `int(_loc6_.length)`，null → NPE | Array，`_page_num = ranks.length` | — |

**`ranks[i]`**（`RingTopUI.as:224-238` → `TopItem.data` `TopItem.as:116-158`）

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `rank` | 直接读 `:226,230` | int 名次；**必须 `<= 100`**，否则该行 `data = null` 置灰（`:226-238`）。`0 < index < 4` 时加载 `img_top_<index>` 冠名图标（`TopItem.as:126-128`） | — |
| `id` | 直接读 `:229` | int gid → `TopItem.data.gid` → 点击时发 `FRIEND_INFO_KEY{gid,psk:3}`（`RingTopUI.as:199-202`） | — |
| `name` | 直接读 `:231` → `TopItem.as:123` `_name_txt.text = param1.name`（**Text.text 直接赋值，null 显示 "null"**） | String 昵称 | — |
| `img` | 直接读 `:232` → `TopItem.as:125` `_skin.items = param1.skin` → `ShowItem.as:36-40` **null 会被安全吞掉**（`if(param1==null){removeAll();return;}`） | String 下划线造型串 | `skin.txt`（`z` 列） |

翻页上限硬编码 `_page < 13`（`RingTopUI.as:187`）→ **最多 13 页 × 8 = 104 名**，与 `rank<=100` 过滤一致。

### 4.4 最小可用 JSON 骨架

```json
{"refresh_time":3600000,"arena_rank":7,
 "ranks":[{"id":10001,"name":"第一名","img":"1001_1002","rank":1},
          {"id":10002,"name":"第二名","img":"1003","rank":2},
          {"id":10003,"name":"第八名","img":"1004","rank":8}]}
```

---

## 5. `81 ARENA_REWARD_KEY` — 竞技场积分宝箱

### 5.1 发送点

`ui/GameUI.as:266` `onMouseUpTop2()` — 无参（主界面「竞技场宝箱」按钮，受 `FUN_41` 开关控制 `GameUI.as:301-308`）

### 5.2 消费点

**不走页面跳转**，`MainUI.as:132-139` 直接弹 `TipItem`：

```
_loc4_ = GameUtil.getBox(param2);
_loc3_ = new TipItem(); _loc3_.show(_loc4_);
```

### 5.3 响应字段穷尽清单

**整个响应体就是一个 `getBox` 对象**（`GameUtil.as:575-622`），`switch(param1.box_type)`：

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `box_type` | **无保护** `:578` switch，null 落空 → 返回 **null** IconItem；`TipItem.show(null)` 安全（`TipItem.as:151` `if(data is String)` 为假，跳过 String 分支） | int，1=道具 2=宠物 3=银两 4=水晶；**其他值静默返回 null**，弹窗空白 | — |
| **`box_type==1`** | | | |
| `id` | **无保护** `:583` | int → **`pic.txt[id].iconId`**，拼成 `"p"+iconId`；**表中无此 id 则 iconId 为空串 → `getDefinition("p")` 返回 null → 后续 `new null()` NPE** | `pic.txt` |
| `num` | **无保护** `:584` `getNumber1(param1.num)` 签名收 int | int 数量 | — |
| **`box_type==2`** | | | |
| `id` | **无保护** `:593` | int → **`pet.txt[id].iconId`** | `pet.txt` |
| `num` | **无保护** `:594` | int 数量 | — |
| **`box_type==3`** | `if(param1.point)` `:600` | | |
| `point` | 有保护 | int 银两 | — |
| **`box_type==4`** | `if(param1.crystal)` `:611` | | |
| `crystal` | 有保护 | int 水晶 | — |

### 5.4 最小可用 JSON 骨架

```json
{"box_type":1,"id":10006,"num":2}
```

---

## 6. `82 ARENA_STAR_CONFIRM_KEY` — 竞技场之星确认

### 6.1 发送点

| 位置 | 参数 |
|---|---|
| `ui/GameUI.as:261` `onMouseUpTop1()` | 无参（受 `FUN_40` 开关，`GameUI.as:293-300`） |
| `ui/RingTopStarUI.as:161` `send()` | 无参；`request()` `:242-245` 与 `TipItem` 关闭回调 `:237-240` 都会重发 |

### 6.2 消费点

`MainUI.as:140-143` → `flow(GAME_RING_STAR)` → `Navigator.as:405-407` `RingTopStarUI` → `ui/RingTopStarUI.as:178`

### 6.3 响应字段穷尽清单

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `id` | 直接读 `:180` 存 `this.data.id` | int 星主 gid | — |
| `name` | **无保护** `:181,183` 字符串拼接 | String 星主昵称，`ui.txt[329]` 的 `[s]` 占位符替换它 | — |
| `is_reward` | **无保护** `:185` `if(param2.is_reward)`，null → 隐藏领取按钮 | bool，true 才显示可领取 | — |
| `img` | **无保护** `:193` `_player.data = {"skin":param2.img}` → `Player` 的 skin 处理 | String 造型串 | `skin.txt` |

### 6.4 最小可用 JSON 骨架

```json
{"id":10001,"name":"星主昵称","is_reward":true,"img":"1001_1002"}
```

---

## 7. `83 ARENA_STAR_REWARD_KEY` — 之星奖励领取

### 7.1 发送点

`ui/RingTopStarUI.as:166` `onMouseUpReceive()` — 无参

### 7.2 消费点

**不走 MainUI switch**（83 未列出）→ `MainUI.as:317-318` `default:` → 投给当前页（此时正是 `RingTopStarUI`）→ `ui/RingTopStarUI.as:195`

### 7.3 响应字段穷尽清单

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `top_star_name` | **无保护** `:199` 字符串拼接进 `ui.txt[330]+ui.txt[106]` 的 `[s]` | String 新星主昵称 | — |
| `reward_goods_id` | 间接：`:209` `getConfigObject("pic", param2.reward_goods_id)` **未做 toString**，`Config.getSObject` 内部 `config.get(param1)`（`Config.as:212-219`）→ null 则整块图标被跳过（`:210` 有判空，安全） | int → `pic.txt[id]`；**建议发字符串** `"10006"` 更稳 | `pic.txt` |
| `reward_goods_num` | 间接 `:215` | int 数量 | — |
| `pic` | 有保护 `:229` | Array，插画获得弹窗，项结构见 §9.4 | `pic.txt` |

**注意**：`reward_goods_id` 在 `:209` 没有包 `""`，若发 JSON number，`ArrayList.get(int)` 与 `get(String)` 的键类型可能不匹配导致取不到（返回 null 只是**不显示图标**，不崩）。

### 7.4 最小可用 JSON 骨架

```json
{"top_star_name":"新星主","reward_goods_id":"10006","reward_goods_num":1}
```

---

## 8. `97 RAGE_REWARD_KEY` — 怒气宝箱领取

### 8.1 发送点

| 位置 | `ttype` | 触发页 |
|---|---|---|
| `item/FightResultItem.as:903` | `1` | 竞技场结算（`ARENA_KEY` 分支的宝箱按钮，`FightResultItem.as:403-409`） |
| `ui/DevelopResultUI.as:367` | `2` | 培养结果（`DevelopResultUI.as:324-330` 的 `BboxItem2` 按钮） |

**`ttype` 是唯一必传参数**，两个消费点都靠它区分奖励池。

### 8.2 消费点

97 未列于 `MainUI.readDatas` switch → `MainUI.as:317-318` `default:` → 投给**当前页**，两个页各自实现：

- `ui/RingResultUI.as:522-540` — 竞技场
- `ui/DevelopResultUI.as:338-356` — 培养

两者代码几乎逐行相同。

### 8.3 响应字段穷尽清单

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `box_type` | **无保护** `RingResultUI.as:578`→`GameUtil.as:578` switch | 同 §5.3，1/2/3/4 | — |
| `id` / `num` | 同 §5.3 | 同 §5.3 | `pic.txt` / `pet.txt` |
| `point` / `crystal` | 同 §5.3 | 同 §5.3 | — |
| `pic` | **有保护但有坑**：`RingResultUI.as:536` `if(param2.pic)` 在 `if(param2)` 块**之外**（`:525-535` 是 `if(param2)`）。若 `param2` 整体为 null，`:536` 的 `param2.pic` 直接 NPE | Array | `pic.txt` |

**关键差异（对比 §5）**：97 会额外消费 `pic`，且 81 不会。所以 97 的响应体是「box 对象 + 可选 pic 数组」的合流。

### 8.4 最小可用 JSON 骨架

```json
{"box_type":3,"point":5000,"pic":[{"id":10006,"icon":"10006","reward_point":0,"reward_crystal":0,"reward_money":0,"reward_goods":[]}]}
```

---

## 9. `56 TITLE_INFO_KEY` — 称号详情

### 9.1 发送点

`ui/TitleUI.as:158` `onMouseUpItem()` — `{"gid": <TitleItem.data.gid>}`

### 9.2 消费点

`MainUI.as:164-167` → `flow(CITY_UNION_TITLE_INFO)` → `Navigator.as:531-533` `TitleInfoUI` → `ui/TitleInfoUI.as:155`

### 9.3 响应字段穷尽清单 —— **⚠ 与其他命令根本不同：响应不是对象，而是逗号分隔的字符串**

```actionscript
var _loc3_:Array = param2.split(GameUtil.separated1);   // TitleInfoUI.as:157  separated1 = ","
```

`param2` 本身是 JSON.parse 的结果，因此服务端必须让 JSON 解析出一个 **String**。`JSON.parse("\"a,b,c\"")` → String → `.split(",")` 成功。
（`JSON.parse("[...]")` 会给 Array，Array 也有 `.split` → TypeError。）

**因此服务端的第 2 段要写成 `"\"gid,name,reward,info,get\""`（带引号的转义字符串），而不是裸的 `gid,name,...`。**

| 下标 | 字段 | 判空 | 语义 | 行号 |
|---|---|---|---|---|
| `_loc3_[0]` | `gid` | **无保护** `:158` 存 `_data.gid`，`:172` 直接发 `SHOP_BUY_KEY{gid}` | String 商品 id（购买用） | `:158` |
| `_loc3_[1]` | `name` | **无保护** `:159` `"" + _loc3_[1]` → undefined 显示 "undefined" | String 称号名 | `:159` |
| `_loc3_[2]` | `reward` | **无保护** `:161` 同上 | String 获得条件说明 | `:161` |
| `_loc3_[3]` | `info` | **无保护** `:160` 同上 | String 称号描述 | `:160` |
| `_loc3_[4]` | `get` | 有保护 `:162` `if(_loc3_[4])`；`:164` `int(...)==1` 才显示购买按钮 | **"1"=可购买**，其他/空=不显示 | `:162-165` |

**必须恰好 5 段**——第 5 段缺省会得到 undefined，`if` 判空通过但 `int(undefined)=0`，按钮不显示，不崩。

### 9.4 关联：TitleUI 列表（无命令，纯本地）

`TitleUI.readDatas` **是空实现**（`TitleUI.as:161-163`），且 `send()` 也是空实现（`:133-135`）。列表永远 12 个「未开放称号」占位（`TitleItem.as:87-89`）。这不是你的 501 原因，但也说明称号系统在本版本是未完工的桩。

`SHOP_BUY_KEY`(29) 的购买回包未被 `TitleInfoUI` 接收——它会落到 `MainUI.as:317-318` default 投给 `TitleInfoUI`，而 `TitleInfoUI.readDatas` 无条件执行 `.split(",")`，若你给 29 返回对象就会 NPE。**建议 29 也返回同样格式的逗号串。**

### 9.5 最小可用 JSON 骨架

第 2 段原文：`"10001,无上荣光,击杀100只精英,永久提升10点攻击,1"`
即响应 body 全文：

```
56\t"10001,无上荣光,击杀100只精英,永久提升10点攻击,1"
```

---

## 10. `72 UP_ROLE_KEY` — 职业升级（转职）

### 10.1 发送点

`ui/ChangeJobInfoUI.as:159` `onMouseUpChangeJob()` — `{"gid": <this.data.gid>}`，其中 `this.data.gid` 由 `readDatas` 从 **`param2.job`** 存入（`ChangeJobInfoUI.as:178`）。即 gid 实际就是 job id。

### 10.2 消费点

**不走 MainUI switch**（72 未列出）→ `MainUI.as:317-318` `default:` → 投给当前页 `ChangeJobInfoUI` → `ui/ChangeJobInfoUI.as:171`

### 10.3 响应字段穷尽清单

`readDatas` 首行守卫 `:171 if(param1 == UP_ROLE_KEY)`，命中即弹窗后 `return`，**其余字段一个都不读**。

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `job` | **间接无保护** `:174` `GameUtil.getConfigValue("upRole", "" + this.data.gid, "name")`，用的是 **UI 缓存的 data.gid**，不是响应字段 → 弹窗文案 | String | `upRole.txt` 的 `name` 列 |

**响应体可以是空对象 `{}`** —— 只要回包第 1 段是 `72`。但 `getConfigValue` 查不到时返回空串（`GameUtil.as:331-334`），弹窗会变成「」的空文案。

### 10.4 最小可用 JSON 骨架

```json
{}
```

**配套：71 UP_ROLE_INFO_KEY**（`ChangeJobInfoUI.readDatas` 的 else 分支 `:178-219`）——转职详情页，同样不在 MainUI switch，字段完整列在这里因为 72 的 `gid` 来自它：

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `job` | **无保护** `:180` | int 目标职业 id → `upRole.txt[job].name` | `upRole.txt` |
| `need_lv` | 有保护 `>0` `:182` | int 需求等级，否则不显示该行 | — |
| `diff_lv` | 有保护 `>0` `:186` | int 等级差，否则不显示该行 | — |
| `nextRole` | **无保护** `:191` `_loc10_.now_hp` | Object，**6 组 now→next 属性对，缺任一即 "undefined"** | — |
| `nextRole.now_hp / next_hp` | `:193` | int 生命 | — |
| `nextRole.now_speed / next_speed` | `:194` | int 速度 | — |
| `nextRole.now_phy_att / next_phy_att` | `:195` | int 物攻 | — |
| `nextRole.now_phy_def / next_phy_def` | `:196` | int 物防 | — |
| `nextRole.now_mag_att / next_mag_att` | `:197` | int 法攻 | — |
| `nextRole.now_mag_def / next_mag_def` | `:198` | int 法防 | — |
| `reward_goods` | 有保护 `:200` | Array，**逐项无判空** `:207-210`，null 项 → NPE | — |
| `reward_goods[].id` | `:210` | int → `pic.txt[id].iconId` | `pic.txt` |
| `reward_goods[].num` | `:211` | int | — |

```json
{"job":2,"need_lv":30,"diff_lv":5,
 "nextRole":{"now_hp":100,"next_hp":150,"now_speed":10,"next_speed":15,
             "now_phy_att":20,"next_phy_att":35,"now_phy_def":10,"next_phy_def":18,
             "now_mag_att":5,"next_mag_att":22,"now_mag_def":8,"next_mag_def":16},
 "reward_goods":[{"id":10006,"num":1}]}
```

---

## 11. `41 SHOW_MORE_INFO_KEY` — 战斗/事件流水

### 11.1 发送点

`ui/InfoUI.as:173-177` `send()` — `{"p":_page, "n":_item_num(9), "ttype":int(data.ttype)}`
`ttype` 由 tab 决定（`InfoUI.as:190-200`）：`"1"`→7、`"2"`→6、`"3"`→2。初值来自 `Navigator.item.data`，见 `MainUI` default 分支外的调用方。

### 11.2 消费点

`MainUI.readDatas` 未列 41 → `MainUI.as:317-318` `default:` → 当前页 `InfoUI` → `ui/InfoUI.as:222`
（特例：`REQUEST_ALOWN_FRIEND_KEY`(513) 走 `InfoUI.as:227-231`，回调 `request()` 重发 41）

### 11.3 响应字段穷尽清单

| 字段 | 判空 | 语义 |
|---|---|---|
| `list` | **无保护** `:232-234` `int(_loc8_.length)`，null → NPE | Array，`_page_num = list.length` |

**`list[i]`**（`InfoUI.as:237-314`）

| 字段 | 判空 | 语义 | 分支 |
|---|---|---|---|
| `type` | 直接读 `:261,281,289,311` | int，回传给 `REQUEST_ALOWN_FRIEND_KEY{index,ok}` 的 `type` 语境；`InfoItem.data.ttype == 7` 才显示确认/拒绝按钮（`InfoItem.as:50`） | 全部 |
| `id` | 直接读 `:262` 等 | int，`REQUEST_ALOWN_FRIEND_KEY.index`（`InfoItem.as:135,142`） | 全部 |
| `target_name` | **无保护** `:250,257,270,275,287,306` 全部进 `.replace("[s]",…)` | String 对方昵称。null → `"null"` 文本 | 全部 |
| `time` | **无保护** `:259,278,308` 直接拼 | String 已格式化时间（**服务端预格式化，不是时间戳**） | ttype 2/6/7 |
| `is_win` | 有保护三元 `:249,256,249` | bool | ttype==2 |
| `value` | 直接读 `:247,267,274,307` | **多义**，见下 | 全 |
| `target_pet_name` | 有保护 `:251` | String，回落 `pet.txt[target_pet_id].name` | ttype==2 |
| `target_pet_id` | 直接读 `:251` | int → `pet.txt` | ttype==2 |
| `pet_name` | 有保护 `:252` | String，回落 `pet.txt[value].name` | ttype==2 |
| `target_id` | 直接读 `:287`（拼进 `event:` 链接） | int/String 供 `FRIEND_INFO_KEY{gid,psk:4}`（`InfoItem.as:126-129`） | ttype==7 |

**`value` 的取值域按 `switch(_loc5_ - 2)`（`_loc5_` = 请求的 ttype）**：

| ttype | `value` 语义 | 行号 |
|---|---|---|
| **2**（战斗） | `0` → 非 PVP（ui.txt 608/607）；`!=0` → PVP（ui.txt 606/605），且此时 `value` 同时是**我方宠物 id** 回落 `pet.txt[value].name`（`:252`） | `:244-265` |
| **6**（帮派） | `0` → 加入(ui.txt 601)；`!=0` → 挑战职位(ui.txt 602)，`getGuildPost(value)`，`value-1` 映射 ui.txt 93..99（`GameUtil.as:438-459`） | `:266-284` |
| **7**（好友申请） | **不读 value**，只拼 `target_id/target_name` 的可点链接（ui.txt 600） | `:285-293` |
| **其他** | **⚠ 默认分支有 bug**：`switch(int(_loc7_[0]) - 3)` 读的是**数组第 0 项**而非 `_loc7_.value`（`:295`） | `:294-313` |

由于这个 `int(_loc7_[0])` 恒为 `0`（`0-3=-3`，无匹配 case），`_loc3_` 保持 `""`，随后 `.replace` 安全无操作，再拼 `target_name` + `value` + `time` —— 即只显示时间。任何 ttype 不属于 {2,6,7} 的请求都会走这条降级路径。

### 11.4 最小可用 JSON 骨架（ttype=2）

```json
{"list":[{"id":501,"type":2,"target_name":"路人甲","target_pet_name":"烈焰狐",
          "target_pet_id":2001,"pet_name":"","value":0,"is_win":true,"time":"2026-10-20 15:04"},
         {"id":502,"type":2,"target_name":"路人乙","target_pet_name":"",
          "target_pet_id":0,"pet_name":"玄冰狼","value":2003,"is_win":false,"time":"2026-10-20 16:11"}]}
```

---

## 12. `49 PICSTEP_REWARD_KEY` — 插画收集阶段奖励

### 12.1 发送点

`ui/IllustrationTaskUI.as:363` `onMouseUp()` — 无参（按钮可见性由 48 的 `is_finish` 决定，`:262-265`）

### 12.2 消费点

49 未列于 `MainUI.readDatas` switch → `MainUI.as:317-318` `default:` → 当前页 `IllustrationTaskUI` → `ui/IllustrationTaskUI.as:267`

### 12.3 响应字段穷尽清单

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `reward_point` | 有保护 `>0` `:270` | int 银两 | — |
| `reward_money` | 有保护 `>0` `:281` | int 元宝（图标 `img_gold_0`） | — |
| `reward_crystal` | 有保护 `>0` `:292` | int 水晶 | — |
| `reward_goods` | 有保护 `:303` | Array，**逐项判空** `:311`（比其他 UI 更稳） | — |
| `reward_goods[].id` | 直接读 `:315` | int → **`pic.txt[id].iconId`**（注意：48 的同类字段查的是 `prop.txt`，49 查 `pic.txt`） | `pic.txt` |
| `reward_goods[].num` | 直接读 `:316` | int 数量 | — |
| `pic` | 有保护 `:341` | Array，插画获得弹窗 | `pic.txt` |

**注意**：`reward_money` 的判定与 `reward_point` 完全相同（都是 `>0`），但 `:281` 的判定对象是 `reward_money`，没有符号错误。

### 12.4 `pic[]` 每一项的完整契约（GetPicItem，§9.3/§9.4 复用同一结构）

`GameUtil.getPic`（`GameUtil.as:534-553`）→ 每项喂给 `GetPicItem.readDatas`（`item/GetPicItem.as:148-264`）：

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `icon` | **无保护** `:170-175`：`getDefinition("p" + icon)` 包在 try/catch 里，**catch 后 `_loc2_` 仍为 null，紧接着 `new _loc2_()` 必 NPE** | **String** 造型码，`"p"+icon` 拼类名 | `skin.txt` |
| `id` | `:184-196` 四级回落 `pic` → `pet` → `prop` → `exploreEquip`；**全 miss 时 `_loc5_` 为 null，`:197` `_loc5_.get("name")` 必 NPE** | int 主键 | `pic.txt`/`pet.txt`/`prop.txt`/`exploreEquip.txt` 的 `name` 列 |
| `reward_point` | 有保护 `>0` `:200` | int | — |
| `reward_crystal` | 有保护 `>0` `:211` | int | — |
| `reward_money` | 有保护 `>0` `:222` | int（**图标下的数字错用了 `reward_crystal`**，`:227` 是原游戏的复制粘贴 bug） | — |
| `reward_goods` | 有保护 `:233` | Array，逐项判空 `:241` | — |
| `reward_goods[].id` | `:245` | int → `prop.txt[id].iconId` | `prop.txt` |
| `reward_goods[].num` | `:246` | int | — |

### 12.5 最小可用 JSON 骨架

```json
{"reward_point":3000,"reward_money":0,"reward_crystal":20,
 "reward_goods":[{"id":10006,"num":1}],
 "pic":[{"id":10006,"icon":"10006","reward_point":1000,"reward_crystal":0,"reward_money":0,"reward_goods":[]}]}
```

---

## 13. `1 OWN_INFO_KEY` — 刷新金币

### 13.1 发送点

`ui/ShopPayUI.as:323` `onActivate()` — 无参。**唯一发送点**：AIR 应用从后台激活时回查金币。

### 13.2 消费点

1 未列于 `MainUI.readDatas` switch → `MainUI.as:317-318` `default:` → 当前页 `ShopPayUI` → `ui/ShopPayUI.as:326-333`：

```actionscript
GameUtil.gold = "" + param2.money;              // ← 唯一读的字段
_gold_icon.data = {"num": GameUtil.gold, "scale": 0.75};
```

### 13.3 响应字段穷尽清单

| 字段 | 判空 | 语义 | 来源表 |
|---|---|---|---|
| `money` | **无保护** `:328` `"" + param2.money` → 显示 "undefined" | int/string 元宝余额 | — |

**只有一个字段。** 缺了不会崩，只是金币图标显示 "undefined"。

注意：`GameUtil.gold` 是全局缓存，`LoginUI.as:176`/`CreateUI.as:434`/`HomeUI.as:194`/`ShopInfoUI.as:406` 都会写它，所以字段名必须严格是 `money`（与登录/角色信息同名字段），不能叫 `gold`。

### 13.4 最小可用 JSON 骨架

```json
{"money":12800}
```

---

## 14. 汇总：易踩坑清单

| # | 坑 | 说明 |
|---|---|---|
| 1 | 响应必须是 `<cmd>\t<json>` | 纯 JSON 会被 `JSON.parse` 成对象后再 `.split("\t")` 拿到 `[object Object]`，直接坏 |
| 2 | 错误用 `-1:<id>` 而非 HTTP 状态码 | `error.txt[0]` 才是「网络错误」；HTTP 5xx 走 `ioError`，语义不同 |
| 3 | **56 是逗号串不是对象** | 唯一一个 `param2.split(",")` 的命令；JSON 层要写成带引号的转义字符串 |
| 4 | `img`（24/74 的 att_list）是下划线串，`img`（def_list）是单值 | 混用会导致 `ShowItem`/`Pet` 取不到类而 NPE |
| 5 | `record[].att.code` 必须 ∈ [0,2] | 越界得 undefined，`FightProcess.as:137-138` NPE |
| 6 | 24/74 的 `att_list[0].img`、`def_list[0].img` 无判空 | `att_list[0]` 整体为 null 时 `:290` / `:338` 立刻 NPE |
| 7 | `24` 缺 `arena_ap`/`max_arena_ap`/`rage_point` → 结算页显示 "undefined/undefined" 和 0% 宝箱灰化 | 均为无保护读取 |
| 8 | 507 `ranks[].rank > 100` 整行被丢弃 | 排行榜硬上限 100 名 |
| 9 | 73 `maps` 为 null → NPE | 无判空 |
| 10 | `pic[].icon` 拼类名 `"p"+icon` 且 `new null()` 之前无判空 | `icon` 必须是合法影片名 |
| 11 | `pic[].id` 四表全 miss → `_loc5_.get("name")` NPE | 至少要命中 `pic.txt` |
| 12 | 72 响应体可为空对象 `{}` | 只看回包 cmd |
| 13 | 83 的 `reward_goods_id` 建议发字符串 | 代码没做 `""+` 转换 |
| 14 | 97 的 `pic` 判定在 `if(param2)` 块外 | 响应体不能是 null/无值 |

---

## 15. 附：`24`/`74` 可复用性最终判定

> **可以复用。**
>
> `AbyssResultUI.readDatas` 的 `att_list` / `def_list` / `record` 三段解析与 `HunterResultUI.readDatas`（`ui/HunterResultUI.as:340-` 及 `record` 循环）以及 `RingResultUI.readDatas` 在**字段名、嵌套层级、类型强转方式上逐字节一致**——包括 `int()` 强转位置、`t=1/2` 的攻守标记、`effect_turn` 的透传方式。三者共用同一个 `FightProcess` 状态机（`FightProcess.as:14-34`），所以服务端只需实现**一个**战斗回放生成器，按 `showId` 产出同一套结构即可覆盖 6 / 24 / 74。
>
> 唯一需要按命令分叉的是**结算面板层**（`FightResultItem.readDatas` 的 `HUNT_KEY`/`ARENA_KEY`/`COPY_BATTLE_KEY` 三个分支，`FightResultItem.as:158/339/420`）与 74 独有的宠物升级与 `pic` 字段。