# 擂台防守快照 + 装备分套 设计说明

- 日期：2026-10-25
- 状态：待用户确认（本文件只做设计，不改代码）
- 范围：PvE 出战配置与擂台防守配置分离；装备/宠物的点击切换交互
- 不在本规格内：真实异步 PvP 匹配、战报回放、擂台排名算法、客户端补丁实现

## 一、问题

当前服务端只有一套“穿着”：

- 装备：`inventory.equipped=1` 是全局唯一的一套（武器/衣服/帽子）。
- 宠物：PvE 三模式（6 狩猎 / 74 副本 / 103 探险）已改为读 `pets.squad_slot`；
  擂台 24/506 仍按 id 最小两只，刻意没跟 PvE 走。
- 506 是“试炼对手”展示：角色用基础皮肤、宠物拿玩家列表克隆并统一标 Lv5，
  不是玩家的真实防守队伍。

问题在于：擂台是**异步 PvP**。别人打你时你不在线，不能用你当前打怪的装备/宠物。
如果 PvE 和擂台共用一套，会出现：

1. 你为了打怪换了装备，防守强度偷偷变化；
2. 别人看到的战报和你面板上的当前装备对不上；
3. 你为了防守不敢换 PvE 装备，或为了 PvE 放弃防守。

所以“全局统一”不成立。要统一的是**交互方式**，不是**数据**。

## 二、目标

1. **PvE 一套**：6 狩猎 / 74 副本 / 103 探险共用“3 件装备 + 2 只宠物”；
   在任意 PvE 页面改了，另外两处一致。
2. **擂台防守一套**：单独保存“3 件装备 + 2 只宠物”的快照；别人打你时读快照，
   不随 PvE 变化。玩家在擂台页手动“保存防守”才更新。
3. **擂台进攻**：第一版复用当前 PvE 配置，减少一套 UI；以后需要再拆。
4. **点击交互一致**：所有纸娃娃页面，点人物进对应装备配置，点宠物槽卸下/切换，
   点已穿部位先卸下再选新装备；但 PvE 页面编辑 PvE，擂台页面编辑防守快照。
5. **老存档不变**：没有防守快照时回退当前 PvE；不强制玩家立刻配置。

## 三、配置模型

| 配置 | kind | 内容 | 谁读 |
|---|---|---|---|
| PvE 出战 | `pve` | 3 件装备 + 2 只宠物 | 6 / 74 / 103 |
| 擂台防守 | `arena_defense` | 3 件装备 + 2 只宠物 | 506 展示、未来的防守结算 |
| 擂台进攻 | 暂复用 `pve` | 同上 | 24 主动挑战 |

规则：

- `pve` 继续用现有的 `inventory.equipped=1` 与 `pets.squad_slot`，**不复制数据**，
  避免老存档迁移和双写。
- `arena_defense` 单独存一份引用；不修改 `inventory.equipped` 和 `pets.squad_slot`。
- 没有 `arena_defense` 行：读取时回退当前 `pve` 的装备/宠物（只读回退，不自动写行）。
- 擂台防守保存后，PvE 再换装备/宠物不影响它；玩家点“同步当前 PvE”才覆盖。

## 四、数据模型

新增一张表，只加表，不改既有列：

```sql
CREATE TABLE IF NOT EXISTS player_loadouts (
    player_id       INTEGER NOT NULL,
    kind            TEXT    NOT NULL,              -- 'arena_defense'
    weapon_inv_id   INTEGER NOT NULL DEFAULT 0,    -- inventory.id（实例，不是 item_id）
    clothes_inv_id  INTEGER NOT NULL DEFAULT 0,
    hat_inv_id      INTEGER NOT NULL DEFAULT 0,
    pet1_id         INTEGER NOT NULL DEFAULT 0,    -- pets.id（实例）
    pet2_id         INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT    NOT NULL,
    PRIMARY KEY (player_id, kind)
)
```

为什么存 `inventory.id` 而不是 `item_id`：

- 同一件装备有等级/星级/强化 `pro`/六维，`inventory` 行才是真实数值；
- 纸娃娃又需要 `item_id` 查 `equip.txt` 的 `imageId`；
- 用实例 id 可以同时满足数值和外观，且不会把两件同名装备搞混。

读取时的有效性：

- `inventory.id` 必须仍属于该玩家、`team=3`、且未被卖掉；否则该槽视为空。
- `pets.id` 必须仍属于该玩家、未放生、未锁定；否则该槽视为空。
- 槽为空不自动补位；两个宠物槽可以只填一个。

暂不冻结数值：

- 第一版防守按保存的实例 id **实时重算**六维（装备精炼/宠物升级后会变）。
- 如果以后要“完全冻结”，再加 `snapshot_json` 列存当时的六维/技能，不改现有结构。

## 五、服务端读写

### 5.1 读取

新增：

```python
def _loadout_equipment(connection, player_id: int, kind: str) -> dict[int, sqlite3.Row]:
    """kind='pve' -> inventory.equipped=1；kind='arena_defense' -> player_loadouts 的实例 id。"""


def _loadout_pets(connection, player_id: int, kind: str) -> list[sqlite3.Row]:
    """kind='pve' -> pets.squad_slot；kind='arena_defense' -> player_loadouts.pet1/2。"""
```

回退规则：

- `kind='pve'` 完全走现有查询，不改。
- `kind='arena_defense'`：
  1. 有 `player_loadouts(kind='arena_defense')`：按实例 id 取装备/宠物；
  2. 没有：回退 `pve`（只读，不写表）。

`_role_stats` / `_hunter_combat_stats` 增加 `kind` 参数（默认 `'pve'`），
这样面板、PvE 战斗、擂台展示可以各读各的，不再靠全局 `equipped` 猜。

### 5.2 写入

新增两条本地命令（编号待 CommandManager 确认，当前 `_SHOW_HANDLERS` 里 514/515/516 空闲）：

| showId | 语义 | 请求 | 响应 |
|---|---|---|---|
| 515 | 读防守配置 | `uid` | `{kind:"arena_defense", weapon, clothes, hat, pets:[...], updated_at, is_default}` |
| 516 | 保存防守配置 | `uid, weapon, clothes, hat, pet1, pet2` | `{value:"ok", updated_at}` |

- 参数是 `inventory.id` / `pets.id`；0 表示空槽。
- 保存前校验归属和槽位（武器 type=1、衣服 2、帽子 3），不合法回 `-1:100`。
- 保存只写 `player_loadouts`，**不修改** `inventory.equipped` / `pets.squad_slot`。
- 读 515 时如果没有行，返回当前 PvE 的引用并带 `is_default:1`，客户端显示“当前跟随 PvE”。

### 5.3 装备卸下

现有 37 只有“穿上”。建议扩展：

```text
showId=37&action=off&slot=1   # 卸下武器；slot 1/2/3
```

- 不传 `action` 时保持原语义（按 `index` 穿上），老客户端不受影响。
- 卸下只把该槽 `equipped=0`，不删行、不退钱。
- 回包沿用 37 的面板 payload，客户端可直接刷新纸娃娃。

### 5.4 擂台 24/506

- 506：改为读 `arena_defense` 展示防守阵容；没有快照时回退 PvE。
  但当前 506 是“试炼对手”假数据，**在真实 PvP 之前不要直接替换**，
  否则界面语义会从“对手”变成“自己”。建议新增独立的“防守阵容”页，
  506 保持试炼对手不变。
- 24：当前是玩家主动打假对手，不存在“别人打你”的防守结算。
  真实防守结算要等异步 PvP 功能，届时读 `arena_defense`。
- 本规格只把数据和读取路径准备好，**不伪造防守战报**。

## 六、客户端交互（需另开客户端 lane）

统一原则：**同一个手势，在不同页面编辑不同的配置**。

| 页面 | 点人物 | 点宠物槽 | 点已穿装备 |
|---|---|---|---|
| 人物面板 / PvE 页面 | 编辑 `pve` | 44/45 改 `squad_slot` | 先卸下，再开该部位筛选 |
| 擂台防守页 | 编辑 `arena_defense` | 515/516 改防守宠物 | 先卸下防守槽，再开筛选 |

交互细节：

- 点已穿部位：第一次点击 `37&action=off&slot=n` 卸下并刷新；第二次点击打开
  背包该部位筛选（复用 22，`ttype=3` + 槽位过滤）。
- 点空部位：直接打开该部位筛选。
- 点宠物：有宠物 -> 45 卸下；空槽 -> 42 选宠，44 放入。
- 擂台防守页顶部加“当前跟随 PvE / 已自定义”状态和“同步当前 PvE”按钮。
- 所有页面都只改自己那一套，不要用一个全局开关偷偷改另一套。

## 七、兼容与迁移

- 只 `CREATE TABLE IF NOT EXISTS`，不改既有列；老存档启动后自动有表。
- 没有 `arena_defense` 行时，515 返回 PvE 引用，506/未来防守读 PvE；
  行为与现在一致。
- 现有 PvE 改动（6/74/103 读 `squad_slot`）保留；擂台 24/506 暂不跟 PvE 走。
- 装备卸下扩展不改变 37 的旧请求语义。

## 八、测试计划

后端（新增 `server/tests/test_arena_loadout.py`）：

1. 保存防守快照后，改 PvE `equipped` / `squad_slot`，515/防守读取仍是旧快照。
2. 没有快照时，515 回退当前 PvE，并返回 `is_default:1`。
3. 快照里的装备被卖掉/宠物被放生：该槽读成空，不报 500。
4. 保存时传别人家的 `inventory.id` / `pets.id`：拒绝 `-1:100`。
5. 保存武器槽传衣服 id：拒绝 `-1:100`。
6. 37 `action=off&slot=1` 只清武器，不影响衣服/帽子。
7. 老存档（无 `player_loadouts` 行）行为不变。

客户端（另 lane）：

1. PvE 页面点人物/宠物只改 PvE；
2. 擂台防守页点人物/宠物只改防守，并显示“已自定义”；
3. 点已穿装备先卸下、再点开筛选；
4. 桌面截图：PvE 换装后擂台防守不变；点“同步当前 PvE”后才变。

## 九、实施顺序

1. **后端数据层**：建表、`_loadout_equipment` / `_loadout_pets`、`_role_stats(kind)`、515/516、
   37 `action=off`；测试 1-7。不碰 506/24 的显示。
2. **擂台防守页**：客户端 lane 加页面与点击，读 515/写 516；“同步当前 PvE”。
3. **真实 PvP**：等异步对手/战报设计确定后，24 防守结算读 `arena_defense`；
   506 是否改为防守展示再定，不要和“试炼对手”混用。

## 十、风险与待确认

- **攻击/防守是否要两套**：本规格先“进攻=PvE、防守=快照”；如果用户要三套，
  再加 `arena_attack`，数据模型不变。
- **数值是否冻结**：第一版实时重算；如果怕精炼/升级影响历史防守，再加 `snapshot_json`。
- **506 语义**：当前是试炼对手，不应直接改成玩家防守；建议新页。
- **命令号**：515/516 是本地提议，必须先在 `CommandManager.as` 里确认没有占用；
  客户端不配合时，可先用维护脚本写表验证后端。
- **本地离线服没有真实“别人打你”**：防守快照先做数据与页面，不伪造战报。
