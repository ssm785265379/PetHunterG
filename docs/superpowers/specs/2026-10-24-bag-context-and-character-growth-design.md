# 道具场景过滤 + 人物成长 设计说明

- 日期：2026-10-24
- 状态：待用户评审
- 范围：阶段 1（道具按场景过滤、养成流程修正）+ 阶段 2（人物等级/经验/称号/属性/装备技能显示）
- 不在本规格内：宠物数值/技能进入战斗、擂台 PvP 平衡（阶段 3，另写规格）

## 一、背景与证据

### 1. 道具上下文

- `BagListUI.send()`（AS3:154-164）只发 `{ttype,p,n}`，**不带上下文**。
- 但页面本身有 `data.target`：`HomeUI.as:245-266`、`RoleInfoUI.as:221-224` 用 `target:0`；
  `PetInfoUI.as:541-544` 用 `target:data.index`（宠物）。
- `BagListUI.readDatas`（AS3:279-365）已经按 `use_type` 判过：
  - `target==0`：`use_type 0 → on=-1`、`1 → on=1`、其它 → `on=0`（灰）。
  - `target>0`：`use_type 0/1 → on=0`（灰）、其它 → `on=1`。
  - `ttype==2`（材料）恒 `on=2`。
- 也就是说：**客户端只是把不匹配的道具灰掉，没有隐藏**，而服务端不知道上下文，无法在分页前过滤。
- `prop.txt` 的 `useType` 只有 0/1/2 三种：0=通用/特殊（34 个）、1=人物用（47 个）、2=宠物用（26 个）。

### 2. 训练

- `_training_list`（505，选宠页）返回所有 `battle_state=0` 的宠物，**没排除训练中**。
- `_training_action`（10）只拦“同一只已经在训练”，不处理出战槽。
- 战斗/探险/擂台/副本的宠物查询都只看 `battle_state=0 AND is_locked=0`，**没排除 `train_end > now`**。
- 训练收益在 504 结算时才写入 `pro_*`；`train_gain` 只存了第一列的数值，两列按同一个值发放。

### 3. 人物

- `players` 有 `lv` 但永远是 1；没有 `exp`；`job` 在 `_player_payload` 里硬编码为 1。
- `upRole.txt` 有 120 行（1级猎人…120级猎人），字段：
  - `needLevel`：2 级 400、3 级 600、4 级 800、5 级起 1000；
  - `lowerLevel`：2-4 级 0，5 级起 **999**；
  - `rewardGoods`：10016/10017/12101 宝箱。
- `error.txt:207` = 「转职需要的等级不够」；`ChangeJobInfoUI.as:182-189` 把 `need_lv` 显示为
  「等级条件」、`diff_lv` 显示为「转职后降低等级」。
- 结论（本规格采用，待用户确认）：**等级 1-1000 靠经验自动涨；称号 job 1-120 手动转生**。
  到 400/600/800 转 2/3/4 级称号（不掉级）；到 1000 转 5 级起掉 999 级（回到 1 级），
  拿宝箱和永久属性。`error 207` 用于 72 号转职失败。
- `equip.txt` 自带 `skills`（如烈焰之剑 `101:5101`），`RoleInfoUI.as:158-170` 正好读
  人物面板的 `skills`；当前服务端恒发 `[]`。

## 二、已确认的决策

| 决策 | 选择 |
|---|---|
| 推进顺序 | 阶段 1 + 阶段 2（阶段 3 另写规格） |
| 训练中的宠物参战 | 不能；开始训练自动从出战槽下场 |
| 人物技能 | 先只把已穿装备的 `skills` 汇总显示，不参与战斗 |
| 人物升级方式 | 称号/转生**手动**；等级本身靠经验自动涨 |

## 三、阶段 1：道具按场景过滤

### 3.1 客户端改动（BagListUI）

`send()` 增加 `target`：

```as3
CommandManager.send(CommandManager.BAG_INFO_KEY,{
   "ttype":data.ttype,
   "p":_page,
   "n":_item_num,
   "target":data.target == null ? 0 : data.target
});
```

- 入口缺 `target` 时按 0（人物/家园）处理。
- 这是**唯一的客户端改动**；加进 `rebuild-client-patches.py`，用同一把 localwifi 签名密钥
  重新打包覆盖安装（保留登录状态）。
- 风险：FFDec 对 `BagListUI` 的全量重编译可能失败（`HireListUI`/`Navigator` 有过先例）。
  失败时的退路：客户端本地过滤 + 服务端仍返回全量，分页保持 9 格但允许空位；
  不推荐，仅在无法重编译时启用。

### 3.2 服务端 22 号

- 解析 `target`（缺省 `-1` = 旧客户端，不过滤）。
- 仅当 `ttype==1`（道具）且 `target>=0` 时过滤：
  - `target==0`（人物/家园）→ 只保留 `use_type IN (0,1)`；
  - `target>0`（宠物）→ 只保留 `use_type==2`。
- `ttype==2`（材料）、`ttype==3`（装备）不过滤（材料恒 `on=2`，装备页只从人物入口进）。
- **先过滤再分页**，避免“第 1 页 9 条、第 2 页重复”的老问题；`bag_size` 仍报该 tab 的
  **总行数**（不随场景过滤变化，保持“已用格数/容量”的口径），`goods_list` 只返回过滤后的页。
- 旧客户端不带 `target` → 保持现有全量行为，不会坏。

### 3.3 阶段 1：训练流程

- 505（选宠页）：`WHERE player_id=? AND battle_state=0 AND (train_end IS NULL OR train_end <= now)`，
  训练中的宠物不再出现在列表里。
- 10（开始训练）：
  - 若宠物在出战槽（`squad_slot != 0`），先把 `squad_slot=0` 再开始训练；
  - 训练中不能再被 505/42/44 选中，也不能进战斗。
- 所有战斗入口排除训练中宠物（`AND (train_end IS NULL OR train_end <= now)`）：
  - 5（狩猎任务出战列表）、42（选宠列表）、44（选出战宠）、103（探险队伍）、
    6（狩猎战斗）、24（擂台）、74（副本）、506（擂台对手）。
- 训练收益按列记账：
  - 新增 `pets.train_gain2 INTEGER NOT NULL DEFAULT 0`；
  - 开始训练时分别计算两列的 `min(per_run, 剩余额度)`，存 `train_gain`/`train_gain2`；
  - 504 结算时两列分别加，`train_gain/train_gain2` 清零；
  - 保持“时间结束才加”，结果页的 `add_*_tp` 只是本次预计收益。

## 四、阶段 2：人物成长

### 4.1 数据

```sql
ALTER TABLE players ADD COLUMN exp INTEGER NOT NULL DEFAULT 0;
ALTER TABLE players ADD COLUMN job INTEGER NOT NULL DEFAULT 1;
```

- `lv`：等级 1-1000，自动升。
- `job`：称号/转生 1-120，手动转。
- 现有存档升级：`job` 默认 1、`exp` 默认 0；不改 `lv`。

### 4.2 经验与升级

| 常量 | 值（LOCAL DEFAULT） | 说明 |
|---|---|---|
| `LOCAL_HERO_MAX_LEVEL` | 1000 | 与宠物上限一致 |
| `LOCAL_HERO_EXP_BASE` | 100 | 1→2 级所需 |
| `LOCAL_HERO_EXP_GROWTH` | 10 | 每级递增 |
| `LOCAL_HERO_BATTLE_EXP_BASE` | 200 | 战斗基础人物经验 |
| `LOCAL_HERO_BATTLE_EXP_PER_REF` | 20 | 每个参考等级再加 |

- `hunter_exp_to_next(lv) = 100 + 10*(lv-1)`（1 级 100；400 级 4090）。
- 战斗人物经验 = `200 + 20*reference_lv`，失败给 10%。
- 来源：狩猎 6、探险 103（战斗场）、擂台 24、副本 74；训练/非战斗事件不给。
- `_grant_hero_exp(c, player_id, amount)`：`exp += amount`，循环
  `while lv < 1000 and exp >= hunter_exp_to_next(lv): exp -= need; lv += 1`。
- 升级本身不发奖励（宝箱在转职时发）。
- 为便于真机验证，新增维护脚本 `server/scripts/grant_hero_exp.py`（按 uid 加经验/直接设
  lv/job），不接任何游戏内命令。

### 4.3 属性

```text
mult = 1 + 0.006*(lv-1) + 0.02*(job-1)
base_stat = round(ROLE_BASE_STATS[stat] * mult)
final = base_stat + Σ装备加成
```

- 六维（hp/speed/phy_att/mag_att/phy_def/mag_def）同系数。
- `_role_stats(worn, lv, job)` 成为**唯一口径**：510/2/37 的面板、`_hunter_combat_stats`
  的战斗数值都用它，避免“面板一个数、打起来另一个数”。
- 1 级 1 称号时与当前值一致，不改变现有平衡；等级/称号越高越强。

### 4.4 人物技能（仅显示）

- `_equipment_skills(worn)`：遍历已穿三件装备，读 `equip.txt` 的 `skills` 列
  （`:` 分隔），去重后按数字排序。
- 返回 **`[{"id": 101}, ...]`**：`RoleInfoUI.as:158-166` 调用 `GameUtil.getSkill()`，
  而 `getSkill` 逐项读 `_loc6_.id`（不是纯数字），传整数数组会显示成空。
- `_player_payload` 的 `skills` 改为该列表；`buffs` 维持 `[]`（配置里没有人物特性来源）。
- 不进入 `_battle_side`，不改变伤害。

### 4.5 70/71/72 转职

**70 列表**（分页 `p/n`，每页 9）：

- 120 个 `upRole` 行，返回 `{job, state}`：
  - `job <= 当前 job` → `state=2`（已获得/当前，另一底图，可看）；
  - `job == 当前 job+1` → `state=1`（白底，可点，看需求）；
  - `job > 当前 job+1` → `state=0`（灰底、不可点）。
- 没有 `job+1`（已 120 级）时全 2。

**71 详情**（`gid=job`）：

| 字段 | 内容 |
|---|---|
| `job` | 目标称号 |
| `need_lv` | `upRole.needLevel`（界面显示“等级条件”） |
| `diff_lv` | `upRole.lowerLevel`（界面显示“转职后降低等级”） |
| `nextRole` | `now_*` = 当前 lv/job 的六维；`next_*` = `lv'=max(1, lv-diff_lv)`、`job'=目标` 的六维 |
| `reward_goods` | `rewardGoods` 解析成 `[{id,num}]`，`0` → `[]` |

**72 转职**（`gid=job`）：

- 只允许 `job == 当前 job+1` 且 `lv >= need_lv` 且 `job <= 120`。
- 成功：`lv = max(1, lv - lowerLevel)`、`job = 目标`、发 `rewardGoods`（进背包，堆叠），
  返回 `{"value":"ok","job":job,"lv":lv}`（客户端只弹「转职成[s]」提示）。
- 失败：`-1:207`（「转职需要的等级不够」）；非相邻/越界用 `-1:100`。
- 转职后等级可能回到 1（5 级起），这是**设计行为**，不是 bug。

### 4.6 510/2 面板

- `_PLAYER_ROW_SQL` 增加 `job, exp`。
- `_player_payload`：`job` 用真实值；属性用 4.3 的口径；`skills` 用 4.4；`exp` 一并下发
  （客户端暂不显示，留给后续经验条）。
- `HomeUI` 的「等级/职业」、`RoleInfoUI` 的六维/技能/装备会自动读到真实值。

## 五、阶段 3（仅记录，不在本规格）

- 宠物六维、`grows`、`pro_*`、星级、世代、性格、技能/特性进入战斗公式。
- 人物/宠物技能真正参与伤害与回合。
- 擂台从“打怪物”改为镜像/异步对手，并做平衡。
- 需要单独一份数值规格 + 模拟器/回归基线。

## 六、测试计划

### 阶段 1

1. 22 号：道具 tab 里放 use_type 0/1/2 各若干，`target=0` 只回 0/1；`target=宠物` 只回 2；
   不带 `target` 回全量；过滤后分页正确（第 1 页 9 条、第 2 页不重复）；`bag_size`
   保持该 tab 总行数。
2. 材料/装备 tab 不受 `target` 影响。
3. 505 不返回训练中的宠物；训练开始后 42/44/103/24 都选不到它。
4. 训练开始时自动 `squad_slot=0`。
5. 两列收益分别记账：接近上限时第二列不会超发。
6. 真机：人物/宠物两个入口分别打开背包，确认不显示对方的道具。

### 阶段 2

1. `hunter_exp_to_next` 与 `_grant_hero_exp`：1 级 100 经验升 2 级；溢出继续升；
   1000 级封顶。
2. 狩猎/探险/擂台/副本胜利给人物经验，失败 10%。
3. 510 的 `lv/job/exp/hp/.../skills` 与公式一致；装备技能汇总正确。
4. 70 的 120 条分页与 state（2/1/0）；71 的 need_lv/diff_lv/nextRole/reward_goods。
5. 72：等级不够 → `-1:207`；成功 → job+1、lv 扣 lowerLevel（5 级起 999→最低 1）、
   宝箱进背包；非相邻 → 拒绝。
6. 战斗数值与面板一致：同一角色在 510 的 hp/att/def 等于 `_hunter_combat_stats`。
7. 老存档升级：`exp=0/job=1`，行为不变。

### 设备验证

- 重打包 localwifi（同签名覆盖安装）→ 重新登录状态保留。
- 进人物面板看等级/称号/六维/装备技能；进转职页看 120 个称号与需求；打一场看人物
  经验上涨、回面板等级变化。
- 背包两个入口分别确认过滤结果。

## 七、实施顺序与提交

1. 阶段 1 服务端 + 测试 → 提交。
2. 阶段 1 客户端 BagListUI 补丁 → 重打包 localwifi → 安装 → 真机验证 → 提交补丁脚本。
3. 阶段 2 数据/经验/属性/技能显示 → 测试 → 提交。
4. 阶段 2 转职 70/71/72 → 测试 → 提交。
5. 更新 `docs/handoff.md`、`docs/design/explore.md`（人物部分）、`CHANGELOG.md`。

## 八、风险与回退

- **BagListUI 重编译失败**：退路是客户端本地过滤（灰的不画），但分页会少格；需要再设计。
- **等级节奏**：`needLevel` 400/600/800/1000 是长线目标；本规格用“本地加快”的战斗经验，
  并用维护脚本跳级验证。数值全部是常量，可单独调。
- **转职掉 999 级**：符合表里的 `lowerLevel`，但对试玩冲击大；如果实测不接受，可把
  `lowerLevel` 的解释改成“保留等级”，只改一个函数。
- **老存档**：只加列、不改 `lv`；`job` 默认 1，不会改变现有战斗数值。
