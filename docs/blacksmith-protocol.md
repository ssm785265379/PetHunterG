# 铁匠铺协议（32/33/34 打造、35 神器强化、36 附魔、77–80 转化熔合）

本文只写**表里查得到**的事实和**本地实现**的规则；两者分开标注：

- 「表内」= `client/air51-repack/src/data/zh-CN/config/*.txt` 或客户端脚本里的确定行为；
- 「LOCAL DEFAULT」= 配置里没有、由本地服务端定的数值/规则，代码里对应 `LOCAL_*` 常量。

证据来源：FFDec 26.4.0 导出 `client/air51-repack/src/APetHunter.swf` 的脚本到临时目录
（`%TEMP%\phg-b12-ffdec`，未入库），下文行号均指导出后的 `.as` 文件。

## 0. 命令与界面总览

| 命令 | 常量（`CommandManager.as`） | 发起的界面 | 服务端实现 |
|---|---|---|---|
| 32 | `GOODS_EXT_LIST_KEY`（:88） | `BlacksmithListUI.as:159-169` | `_forge_list` |
| 33 | `GOODS_EXT_INFO_KEY`（:90） | `MakeInfoUI.as:163-169` / `RefineInfoUI.as:137-143` / `EnchantInfoUI.as:169-175` | `_forge_detail` |
| 34 | `GOODS_MAKE_KEY` | `MakeInfoUI.as:299-302` | `_forge_make` |
| 35 | `EQUIP_REFINE_KEY`（:94） | `RefineInfoUI.as:349-352` | `_forge_refine` |
| 36 | `EQUIP_ENCHANT_KEY`（:96） | `EnchantInfoUI.as:312-316` | `_forge_enchant` |
| 77 | `CHOOSE_MAIN_EQUIP_KEY`（:174） | `IntegrationListUI.as:163-169` | `_synthesis_candidates` |
| 78 | `CHOOSE_VICE_EQUIP_KEY`（:176） | `IntegrationNewListUI.as:160-167` | `_synthesis_candidates(exclude=-1)` |
| 79 | `EQUIP_SYN_CONFIRM_KEY`（:178） | `IntegrationInfoUI.as:166-173` | `_equip_synthesis_confirm` |
| 80 | `SYN_EQUIP_KEY`（:180） | `IntegrationInfoUI.as:303-310` | `_equip_synthesis_perform` |

### 客户端入口（决定了 `ttype` 的语义）

- `BlacksmithUI.as:141-176`：铁匠主页三个按钮 —— 打造 → `ttype=1`，附魔 → `ttype=3`，
  转化熔合 → 77（不进 32）；第四个按钮“神器”进 `ArtifactUI`。
- `ArtifactUI.as:174-178`：“神器强化”按钮 → `CITY_BLACKSMITH_LIST{ttype:2}`。
- 因此 **`ttype=2` 是“神器强化”，不是铁匠主页的第三个 tab**；它的列表页标题取
  `ui.txt` 206「神器强化」，详情页 207「神器强化信息」，成功提示 204「成功强化为」。
- `BlacksmithListUI.as:58-73`：标题 = `ui.txt` 211（打造）/ 206（神器强化）/ 213（附魔装备）。

## 1. 32：列表

请求（`BlacksmithListUI.as:159-169`）：`ttype, loc=0, p, n`，初始页 1，每页 9
（`BlacksmithListUI.as:40-45,90-105`）。

响应：`param2.list[]`，每项读 `index / id / icon / level`（`BlacksmithListUI.as:239-260`），
名字用 `pic.txt[id].name`（:245）。

- `ttype=1`：可打造配方（见第 4 节）。`index` = 配方 id，`id` = 产物 id。
- `ttype=2`：玩家自己的**神器**装备。判定 = `equip.txt` 的 `remark` 含「神器」
  （`57031 初级神器`、`57001 高级神器`、`67001 终级神器`）。因为该列表只从
  `ArtifactUI` 进入，非神器装备不会出现在这里。
- `ttype=3`：玩家自己的、**在 `equipEnchant.txt` 里有行**的装备。没有该行的装备
  （`20001`–`20026` 共 18 件新手/低阶装备）不能附魔，也不列出。

`ttype=2/3` 的 `index` 是 **`inventory.id`**：35/36 原样回传它
（`RefineInfoUI.as:351`、`EnchantInfoUI.as:315`），所以不能用品阶 id 代替
（同一件装备可能有多行）。性别不符的装备不列出（与背包一致，`_equip_matches_sex`）。

## 2. 33：详情

### 2.1 `ttype=1`（打造）

请求 `ttype=1, gid=配方 id`（`MakeInfoUI.as:163-169`）。响应字段见 4.2。

### 2.2 `ttype=2`（神器强化）

请求 `ttype=2, gid=inventory.id`（`RefineInfoUI.as:137-143`）。客户端读：

- `icon, id, star, pro, level` 与六项属性（:187-249）；
- `next_refine.{level,hp,speed,phy_att,mag_att,phy_def,mag_def}` 做绿色差值预览（:195-249）；
- `next_refine.refine_add_skill_level`、`next_refine.refine_skills`（:250-264，>0 才显示）；
- `need_money/own_money`、`need_point/own_point`、`need_crystal/own_crystal`、
  `need_goods[].{id,need_num,own_num}`（:265-314）；
- **没有 `next_refine` 时**打印 `ui.txt` 208「神器达到顶级」（:330-344）——这就是本地
  等级到顶的表现方式，不要下发 `next_refine: null`。

### 2.3 `ttype=3`（附魔）

请求 `ttype=3, gid=inventory.id`（`EnchantInfoUI.as:169-175`）。客户端读：

- `level`（`getLevel`）、`pic.txt[id].name`、`star`（`getStar`）、`pro`（`getFive`）、`icon`；
- `equipEnchant.txt[id].remark` 显示在「附魔上限」框（:197-207）；
- `skills`（`ui.txt` 19「技能」）与 `buffs`（`ui.txt` 20「特性」），逐项读 `.id`
  （`GameUtil.getSkill`，:222-243）；
- 三项货币与 `need_goods`（:244-293）。

本地额外下发（客户端忽略，便于协议自查/测试）：`max_count`、`enchant_count`、
`ext_skills[]`（`{id,min_level,max_level}`，`id` 是该族 1 级技能 id）。

## 3. 表字段语义：`equipEnchant.txt`

表头：`id / needMoney / needPoint / needCrystal / needGoods / maxCount / remark / extSkills / rate`
（最后一列表头带前导空格 `" rate"`，加载时已 strip）。

- `id` = **装备 id**（与 `equip.txt` 同 id，918 行，全部能在 `equip.txt` 找到）。
- `maxCount` = 该装备能持有的**特性条数**；`remark` 就是「N个M等级特性」。
  实测 1–10。
- `extSkills` = `"level1SkillId:minLv-maxLv"` 逗号分隔。`12101` 是 skill.txt
  `1级火系专精`，而 `12110` 是 `10级火系专精`，即**等级 L 的 id = base + L - 1**
  （48 个族全部连续，测试里做了全表校验）。
- `rate` = 每项权重，冒号分隔，**918 行全部求和 10000（万分比）**，所以权重取表内值，
  不需要本地猜。
- `needCrystal` = 水晶货币（error 405「水晶不够」）；`needGoods` = 道具（`10032:1`
  蓝色晶石，252 行；其余为 `0`）。`needMoney/needPoint` 全表为 0，但实现仍按字段扣。
- 这些 id 都是 `skill.txt` 里 `team=2` 的被动特性（专精/抗性/暴击/溅射…），
  与宠物 `pets.buffs` 是同一类 id。

## 4. 打造（32/33/34，P1 已合入）

### 4.1 配方来源

`equip.txt` 的 6 件可打造装备（`25001-25003`、`35001-35003`）加一条本地兼容配方
`32001→20002`。费用 = 表内 `money` 的 10%（`LOCAL_FORGE_FEE_PERCENT`），
材料按品阶取同槽位玉（`LOCAL_FORGE_MATERIAL_BANDS`）。两者都是 LOCAL DEFAULT。

### 4.2 33（打造）响应

`icon,id,star,pro,hp,phy_att,mag_att,phy_def,mag_def,speed` + 可选 `skills/buffs`
（`MakeInfoUI.as:171-229`）；`need_money/own_money`、`need_point/own_point`、
`need_crystal/own_crystal`、`need_goods[].{id,need_num,own_num}`（:231-280）。

> 已知遗留：这里的 `skills` 仍是**裸 id 数组**，而 `GameUtil.getSkill` 逐项读 `.id`，
> 所以「技能」一栏会显示空行。P1 的用例把它钉成了裸数组；P2 的 33/2、33/3 与 39 都按
> `[{"id": …}]` 下发。要修就得同时改 P1 用例，留待专门一次提交。

### 4.3 34：打造事务

只发 `gid`（`MakeInfoUI.as:299-302`）。成功 → `MainUI.as:92-95` 切结果页；
失败按货币：403 金币 / 404 银币 / 405 水晶 / 400 材料 / 300 背包满。事务内扣材料、
扣货币、写产物（同 id 叠行）。

## 5. 35：神器强化（`EQUIP_REFINE_KEY`）

### 5.1 客户端行为

`RefineInfoUI.as:349-352` 只发 `index`（= 列表的 `inventory.id`）。响应只有两处被读：
`level`（`getLevel`）与 `icon`（`p<icon>`），弹一个提示框（:159-186），随后**自己重发 33**
刷新页面。所以 35 成功响应给 `{index,id,icon,level}` 就够。

### 5.2 本地规则（LOCAL DEFAULT，配置里没有强化表）

- 对象：`remark` 含「神器」的装备（与 32 `ttype=2` 列表一致），否则 `-1:406`
  （`error.txt` 406「此装备不能强化」）。
- 等级上限 `LOCAL_REFINE_MAX_LEVEL = 10`；到顶后 35 返回 `-1:408`
  （「此装备已经不能再强化了」），33 不下发 `next_refine`。
- 费用：金币 `500 × 当前等级`（`LOCAL_REFINE_MONEY_PER_LEVEL`）+ 1 个 `11024` 紫色钻石
  （`prop.txt` 备注「可以用于强化神器」）；不足分别 403 / 400。
- 属性：每次 +1 级，六项属性 = `equip.txt` 基础值 × (1 + 5% × (等级-1))
  （`LOCAL_REFINE_STAT_PERCENT`），即 1 级与表内数值完全一致，升级可重算、不漂移。
- 不发 `refine_add_skill_level` / `refine_skills`（保持 0 / 缺省，客户端不显示）。

## 6. 36：附魔（`EQUIP_ENCHANT_KEY`）

### 6.1 客户端行为

`EnchantInfoUI.as:312-316` 只发 `index`（= `inventory.id`）。收到 36 后**用同一套详情
字段重绘**（:177-310），所以成功响应必须是完整详情（等同 33/3 的 payload），否则页面空白。

### 6.2 本地规则

1. 对象必须是 4 星（含）以上、且在 `equipEnchant.txt` 有行的装备：4 星以下回 `-1:9`
   （`error.txt` 9「4星级（含）以上的装备才能附魔」），4 星以上却没有行回 `-1:407`
   （「此装备不能附魔」）。表内 918 行恰好全是 4 星以上装备，两条判定互不重叠。
2. 次数上限 = `maxCount`；已用 = `inventory.buffs` 里已存的特性条数。
   满了返回 `-1:100`（error.txt 没有“附魔次数已满”的键，见第 8 节）。
3. 扣费：`needMoney/needPoint/needCrystal` → 403/404/405；`needGoods` → 400。
   道具按 `prop.txt` 的 `team` 找背包页（`10032` 在道具页 team=1，锻造玉在材料页 team=2）。
4. 抽签：按 `rate` 权重抽一族（表内万分比），等级在该族 `minLv-maxLv` 内**均匀**抽
   （band 内均匀是 LOCAL DEFAULT），写入 id = `base + L - 1`。
5. 写回：**`inventory.buffs`**（冒号分隔 id），不写 `inventory.pro`。
   依据：`EnchantInfoUI` 把 `buffs` 印在 `ui.txt` 20「特性」下，表内 `remark` 也写“特性”；
   `dialog.txt` 14「强化神器获得的特性不会在附魔中消失」说明强化与附魔是两套特性，
   谁都不清空谁。`equip.txt` 的 `skills` 仍是「技能」栏，两者不混。
6. 同族重复抽到：等级更高则**原地顶替**，不额外占 `maxCount` 槽（LOCAL DEFAULT）。
7. 响应 = 附魔后的完整详情（含 `value:"ok"`），`buffs` 里能看到新特性。

装备详情 39（`EquipInfoUI`）也会把 `inventory.buffs` 下发给「特性」栏
（`EquipInfoUI.as:236-243`），离开附魔页后仍能看到结果。

## 7. 77–80：转化熔合（`help.txt` 条目 7）

规则原文（`help.txt` id 7）：只有金币装备能转化熔合；武器/铠甲/头盔只能同类；
同级（同金币价值）收价值 20% 的蓝色晶石，升级转化收双方价值差额；原装备特性转移到
新装备、原装备消失；已装备的不能熔合。`ui.txt` 218 补充「蓝色晶石在金币商店购买」、
「旧装备的附魔属性会继承到新装备上」。

- **蓝色晶石 = `prop.txt` 10032**：其备注是「有了它，金币装备就能进行转化融合了」，
  `error.txt` 423 也专门写「蓝色晶石不足，请到金币商店购买」。
- 同级/升级的产物 id、蓝色晶石与金币的换算率配置里都没有；实现与 LOCAL DEFAULT
  在 P3 的提交里补齐（本文随 P3 一起更新第 9 节）。

### 7.1 77/78 列表

请求 `ttype=2, loc=0, p, n`（`IntegrationListUI.as:163-169`）；78 额外带
`main, loc, p, n`（`IntegrationNewListUI.as:160-167`）。响应 `list[]` 每项
`index / id / icon / loc`（`IntegrationListUI.as:216-238`、`IntegrationNewListUI.as:196-226`），
名字取 `pic.txt[id].name`。

### 7.2 79 预览 / 80 执行

79 请求 `ttype=2, main, vice`（`IntegrationInfoUI.as:166-173`），80 同样参数
（:303-310）。79 的响应被当成“产物属性 + 费用”整页渲染（:175-301）：`id, icon, star,
pro, hp, phy_att, mag_att, phy_def, mag_def, speed`、`skills`、`buffs`、三项货币、
`need_goods[]`。80 的响应只读 `index / id / icon`（`IntegrationResultUI.as:117-131`），
`pic` 可选。

## 8. 错误码

| 场景 | 码 | 依据 |
|---|---|---|
| 参数非法（非数字、缺参） | 100 | `error.txt` 100「非法操作」 |
| 装备行不存在 | 400 | `error.txt` 400「物品不存在」 |
| 附魔：4 星以下 | 9 | 「4星级（含）以上的装备才能附魔」 |
| 附魔：4 星以上但没有 `equipEnchant.txt` 行 | 407 | 「此装备不能附魔」 |
| 强化：对象不是神器 | 406 | 「此装备不能强化」 |
| 强化：等级已到顶 | 408 | 「此装备已经不能再强化了」 |
| 附魔：次数到达 `maxCount` | 100 | 无专用键（本文说明） |
| 金币不足（强化费） | 403 | 403 |
| 银币不足 | 404 | 404 |
| 水晶不足（附魔 `needCrystal`） | 405 | 405 |
| 材料/道具不足（`needGoods`、强化钻石） | 400 | 400 |

只有“附魔次数上限”这一处用 100 兜底，其余都能落到 `error.txt` 的专用键；
这也是客户端会弹出对应文案的地方。P3 的熔合错误码（423/424/425/426）在实现时补入。

## 9. 本地规则汇总（LOCAL DEFAULT）

| 常量 | 值 | 含义 |
|---|---|---|
| `LOCAL_REFINE_MAX_LEVEL` | 10 | 神器强化等级上限 |
| `LOCAL_REFINE_MONEY_PER_LEVEL` | 500 | 每级金币费用 × 当前等级 |
| `LOCAL_REFINE_STAT_PERCENT` | 5 | 每级叠加 `equip.txt` 基础属性的百分比 |
| `LOCAL_REFINE_DIAMOND_ID` | 11024 | 强化材料（表内注明“用于强化神器”） |
| `LOCAL_REFINE_DIAMONDS_PER_LEVEL` | 1 | 每次消耗个数 |
| `LOCAL_ENCHANT_MIN_STAR` | 4 | 附魔的星级门槛（`error.txt` 9） |
| `LOCAL_ENCHANT_LIMIT_ERROR` | 100 | 附魔次数到 `maxCount` 的错误码（强化到顶改用 408） |

## 10. 配置中的 ID（静态事实，不代表当前账号可用）

- 装备：`20001` 烈焰之剑、`20002` 烈焰之铠、`20003` 烈焰之盔（`equip.txt:1-4`）；
  金币武器 `25001` 焚天如意棒（money 3600，`equip.txt`）、`35001` 超级焚天如意棒
  （money 9600）；神器 `57001` 魔王之剑（高级神器，money 298000）、`67001` 超级魔王之剑
  （终级神器，money 298000）。
- 附魔覆盖：`equipEnchant.txt` 918 行，缺的 18 件正是 `20001`–`20026` 新手/低阶装备。
- 材料：`prop.txt` `11001-11009` 玉、`11010` 黑铁石、`11024-11026` 钻石（强化神器）、
  `10032` 蓝色晶石（熔合/高阶附魔）。

## 11. 待验证 / 未验证

- 真机与桌面都还没有对 32/33/35/36、77–80 做过画面验收；本文的协议判断全部来自
  反编译脚本与配置表。
- `ttype=1` 的 33 `skills` 裸数组问题（4.2 节）未修。
- 附魔特性只做展示：未参与战斗数值（`_equipment_skills` 只收 `equip.txt` 技能，
  特性没有进 `_battle_side`）。
- 神器（107/108）只做取证，结论随 P3 的文档更新补入。
