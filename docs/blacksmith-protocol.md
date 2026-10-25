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

### 7.3 本地实现（P3）

`_synthesis_candidates` / `_synthesis_merge` / `_synthesis_fee` 三者是唯一判定处，
79 预览与 80 执行共用 `_synthesis_merge`，不会“预览一套、执行另一套”。

资格（help 7-1/7-2/7-6，全部按表判定）：

- 双方都在 `inventory`（team=3）、不是同一行、`equipped = 0`；
- `equip.txt.money > 0`（金币装备）；新手 `20001-20026` 的 money 为 0，全部不合格；
- `equip.txt.type` 相同（1 武器 / 2 铠甲 / 3 头盔），性别与角色一致；
- 77 列出全部合格装备，78 再按主装备的 `type` 收窄（客户端会把 `loc` 带过来，
  但服务端以 `main` 的实际类别为准，不信任 `loc`）。

费用（help 7-3，单位是 `10032` 蓝色晶石）：

- 同级（`money` 严格相等）：`ceil(money × 20% ÷ 10032.money)`；
- 升级（`money` 不等）：`ceil(|main.money − vice.money| ÷ 10032.money)`；
- 至少 1 枚。`10032.money = 100` 是表内金币单价，换算率本身是 LOCAL DEFAULT。
- 不足返回 **423**（`error.txt` 423「蓝色晶石不足，请到金币商店购买」）。

产物与结算：

- **同级转化**：产物 = 主装备本体（`inventory.id` 不变），属性/等级/星级不动，
  只把副装备的特性并进来；80 响应 `index` = 主装备行 id。
- **升级转化**：产物 = 同类别、同性别、金币价值严格高于**双方较高值**的最低档
  （同档取 id 最小，LOCAL DEFAULT）；产物按 `equip.txt` 属性生成，等级 1。
  80 时**两件原装备都删除**，再插入产物行；若玩家已拥有同 id 产物，
  `UNIQUE(player_id,item_id)` 决定只能叠行——此时 `quantity +1` 并把特性按产物
  `maxCount` 合并进原行（LOCAL DEFAULT）。
- 特性：双方 `inventory.buffs` 按族合并（同族取高等级），按产物
  `equipEnchant.txt.maxCount` 截断；产物没有附魔行则不截断。
- 扣费失败/规则不满足时不写任何一行（`_spend_goods` 在事务内先失败先返回）。
- 错误码全部尽量落到 `error.txt` 的专用键：424 已装备、425 不同部位、426 非金币装备、
  423 蓝色晶石不足；只有“行不存在/同一行”用 400，“已到最高档没有更高产物”用 100
  （`error.txt` 没有对应键）。

## 8. 错误码

| 场景 | 码 | 依据 |
|---|---|---|
| 参数非法（非数字、缺参） | 100 | `error.txt` 100「非法操作」 |
| 装备行不存在 / `main == vice` | 400 | `error.txt` 400「物品不存在」 |
| 附魔：4 星以下 | 9 | 「4星级（含）以上的装备才能附魔」 |
| 附魔：4 星以上但没有 `equipEnchant.txt` 行 | 407 | 「此装备不能附魔」 |
| 强化：对象不是神器 | 406 | 「此装备不能强化」 |
| 强化：等级已到顶 | 408 | 「此装备已经不能再强化了」 |
| 附魔：次数到达 `maxCount` | 100 | 无专用键（本文说明） |
| 金币不足（强化费） | 403 | 403 |
| 银币不足 | 404 | 404 |
| 水晶不足（附魔 `needCrystal`） | 405 | 405 |
| 材料/道具不足（`needGoods`、强化钻石） | 400 | 400 |
| 熔合：蓝色晶石不足 | 423 | 「蓝色晶石不足，请到金币商店购买」 |
| 熔合：已装备 | 424 | 「已装备的物品不能进行装备融合」 |
| 熔合：不同部位 | 425 | 「不同部位的装备，不能进行融合」 |
| 熔合：非金币装备 | 426 | 「非金币装备不能转化熔合」 |
| 熔合：已到最高档、没有更高产物 | 100 | 无专用键（本文说明） |

只有“附魔次数上限”和“没有更高档产物”两处用 100 兜底，其余都能落到 `error.txt`
的专用键；这也是客户端会弹出对应文案的地方。

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
| `LOCAL_SYNTHESIS_PERCENT` | 20 | help 7-3 的同级费率（表内规则，非本地发明） |
| `LOCAL_BLUECRYSTAL_ID` | 10032 | 熔合费用道具（help 7-3/7-4） |
| 蓝色晶石↔金币换算 | `10032.money = 100` | LOCAL DEFAULT：help 只写“20%/差额”，没给枚数换算率 |
| 升级产物 | 同槽位、同性别、价值严格高于双方较高值的最低档（同档取 id 最小） | LOCAL DEFAULT |
| 同级产物 | 保持主装备本体（属性/等级/星级不变） | LOCAL DEFAULT |
| 产物等级 | 同级保留主装备等级；升级从 1 级开始 | LOCAL DEFAULT |
| 产物 `pro` | 沿用主装备 | LOCAL DEFAULT |
| 特性截断 | 按产物 `equipEnchant.maxCount` | 表内上限 |
| 已拥有同 id 产物 | 叠行 `quantity+1`，特性按上限合并 | LOCAL DEFAULT（受 UNIQUE 约束） |

## 10. 配置中的 ID（静态事实，不代表当前账号可用）

- 装备：`20001` 烈焰之剑、`20002` 烈焰之铠、`20003` 烈焰之盔（`equip.txt:1-4`）；
  金币武器 `25001` 焚天如意棒（money 3600，`equip.txt`）、`35001` 超级焚天如意棒
  （money 9600）；神器 `57001` 魔王之剑（高级神器，money 298000）、`67001` 超级魔王之剑
  （终级神器，money 298000）。
- 附魔覆盖：`equipEnchant.txt` 918 行，缺的 18 件正是 `20001`–`20026` 新手/低阶装备。
- 材料：`prop.txt` `11001-11009` 玉、`11010` 黑铁石、`11024-11026` 钻石（强化神器）、
  `10032` 蓝色晶石（熔合/高阶附魔）。

## 11. 神器（107/108）取证：只写证据，未实现

### 11.1 命令与入口

- `107 = ACHIEVEMENT_LIST_KEY`（`CommandManager.as:234`），
  `108 = ACHIEVEMENT_REWARD_KEY`（:236）。
- 入口：`BlacksmithUI.as:152-155` 的“神器”按钮 → `CITY_BLACKSMITH_ARTIFACT` →
  `ArtifactUI`。`ArtifactUI.as:138-172` 的四个分类按钮各发
  `107 {ttype:1..4, p:1, n:9}`；同一页面右下角的“神器强化”按钮
  （:174-178）转到 `CITY_BLACKSMITH_LIST{ttype:2}`，也就是第 5 节的 35。
- `ArtifactListUI` 同时处理 107 的列表响应和 108 的领取响应
  （`readDatas`，:312-398）。

### 11.2 107 的字段（`ArtifactListUI.readDatas:361-397`）

| 字段 | 用法 |
|---|---|
| `id` | 领取时原样作为 `108 {gid: data.id}` 发出（:246、:254） |
| `need_money` | 非 0 时先弹 `ui 412`「再次领取神器需要」并显示 `-need_money` 金币，关闭后再发 108（:205-243） |
| `is_reward` | 为真时点“领取”只弹 `ui 411`；否则走下面的收集检查（:378-394） |
| `pics[]` | 每个元素读 `id` 和 `is_reward`；`index` 只在 `_loc4_[0]` 里被赋值、不参与渲染（:285-310） |
| `pic` | 108 响应里的可选字段，交给 `GameUtil.getPic`（:355-358） |

`pics[]` 的渲染完全走 **`pic.txt`**：`GameUtil.getConfigObject("pic", id)` 取
`name`/`iconId`（:294-301）。进度文字是 `ui 413`「领取神器图鉴完成度 N/M」，
N = `pics` 里 `is_reward` 为真的条数（:369-395）。

领取按钮的三种分支（:196-256、:378-394）：

1. `param2.is_reward` 真 → 弹 `ui 411`「你已经领取完该级别的所有神器」；
2. 不是所有 `pics` 都 `is_reward` → 弹 `ui 410`「收集全上面的图鉴，才能领取神器」；
3. 全部集齐 → 发 `108 {gid: data.id}`。

108 的响应读 `param2.list[]` 的 `{id, num}`（图标取 `pic.txt[id].iconId`）与
`param2.pic`（`ArtifactListUI.as:322-359`）。

### 11.3 数据来源与“激活神器”条件

- **`pic.txt`**：`remark` 为 `初级神器 / 中级神器 / 高级神器 / 终级神器` 的行各 18 条，
  正好对上 `ArtifactUI` 的四个分类按钮：

  | 档位 | pic.txt / equip.txt id |
  |---|---|
  | 初级神器 | `57031-57036`、`57041-57046`、`57051-57056` |
  | 中级神器 | `67031-67036`、`67041-67046`、`67051-67056` |
  | 高级神器 | `57001-57006`、`57011-57016`、`57021-57026` |
  | 终级神器 | `67001-67006`、`67011-67016`、`67021-67026` |

  每个 id 在 `equip.txt` 里也是一件装备（`type` 1/2/3 × `sex` 0/1 × 3 个系列），
  但 107 只把它当“图鉴条目”渲染；`equip.txt` 只提供属性。
- **`task.txt` 没有神器行**（grep「神器」无命中）；`equip.txt` 的 `remark`
  只是「初级/高级/终级神器」，不参与 107 的判定。
- 激活条件（`dialog.txt` 13，NPC 1 的对话）：
  「完成所有的狩猎和探险地图，就能获得激活神器所需要的图鉴」。
  配合 `ui 410`「收集全上面的图鉴，才能领取神器」，即：**打完全部狩猎+探险地图 →
  获得该档 18 张图鉴 → 集齐后领取神器（108）**。Head 的进度分母 18 也由此而来。
  `dialog.txt` 14 另有一条：「强化神器获得的特性不会在附魔中消失」——把 35 与 36
  串起来，也是 P2 把强化/附魔特性分开存放（`inventory.buffs`，互不清空）的客户端依据。

### 11.4 待定（不要当成已确认）

- `ttype 1..4` 与四档的**一一对应顺序**：源码没有常量，只按按钮顺序推断。
- 108 到底发装备本体还是碎片：`pic.txt` 的 `rewardGoods`（初级 `11100:20` 等）
  更像“图鉴奖励”，但发放逻辑在服务端，配置里查不到；本地实现前必须先看真机响应。
- “完成所有地图”的那张 map→pic 产出表不在本仓库的配置里（`worldMap.txt` 只有 238 字节，
  无 pic 列），所以无法离线校验激活前置。
- 神器与 35 的关系只有入口证据（`ArtifactUI` → 32 ttype=2）；36 的附魔表也覆盖神器
  （`57001` 需 7000 水晶 + 1 个 10032），两套特性是否应合并计算仍未验证。

## 12. 待验证 / 未验证

- 真机与桌面都还没有对 32/33/35/36、77–80、107/108 做过画面验收；本文的协议判断
  全部来自反编译脚本与配置表。
- `ttype=1` 的 33 `skills` 裸数组问题（4.2 节）未修。
- 附魔特性只做展示：未参与战斗数值（`_equipment_skills` 只收 `equip.txt` 技能，
  特性没有进 `_battle_side`）。
- 附魔抽签用了 `random`，单测只断言“落在表内 band 里”，没有钉死固定种子。
- 神器（107/108）只做取证，没有实现；见第 11 节。
