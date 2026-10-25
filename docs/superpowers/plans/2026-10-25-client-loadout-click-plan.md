# 点击换装 / 卸下 + 擂台防守页 客户端补丁计划

- 日期：2026-10-25
- 状态：待评审（UI lane 需签字；本文件只做计划，不改 AS3）
- 依赖：T16（PvE 出战宠统一）、T16b（`player_loadouts` + 515/516 + 37 `action=off`）已合入 main
- 范围：PvE 与擂台防守的点击交互；不实现真实异步 PvP

## 一、先纠正一个前提

擂台页 `RingUI` **不是玩家的队伍页**，是“试炼对手”：

- `RingUI.readDatas` 把 `param2.name/lv` 塞给中央 `Player`，把 `param2.pets` 两只塞给左右 `Pet`；
- 中央 `Player` 的外观却用 `GameUtil.skin`（玩家当前皮肤），所以看起来像自己；
- 左右宠物的 `index/name/lv/icon` 来自 506 的对手克隆数据，不是玩家当前出战宠；
- 506 服务端目前返回 `LOCAL_ARENA_RIVAL_NAME / Lv5 / 克隆玩家宠物列表`，是本地假对手。

因此**不能**把“点擂台中央人物/两侧宠物”直接接到玩家的 PvE 装备/宠物上：
那会把“对手”当成“自己”，点一下反而改了玩家 PvE 队伍或防守快照，语义错误。

推荐做法：

- `RingUI` 保持对手展示，只加一个明确的 **「防守阵容」按钮**；
- 点按钮进入新的 `ArenaDefenseUI`，在那里点人物/宠物才是编辑玩家防守；
- PvE 页面（狩猎/探险/副本/人物面板）的点击按 PvE 语义处理。

如果用户坚持“点擂台中央人物就换装”，就必须同时把 506 改成返回玩家防守阵容，
并把标题从“试炼对手”改成“我的防守”，否则界面和语义对不上。本计划不这样做。

## 二、AS3 现状证据

从 `build/as-export` 导出的源码（FFDec `-export script`）：

### 2.1 RoleInfoUI

- `readDatas` 把全部资料拼成一个 `_info_txt` 文本；六维、装备三行都只是字符串。
- `initSkin()` 只创建 `ShowItem` 播放纸娃娃；`_showItem` 没有点击监听。
- `initButton()` 只有返回/主按钮；没有装备槽按钮。
- 结论：要在人物面板点击武器/衣服/帽子，必须**叠加透明 Button**，
  按文本行位置算热区，不能指望现有控件。

### 2.2 RingUI

- `_player.mouseEnabled = false`，中央人物不可点。
- `initButton()` 已经在两只宠物上叠了 `250×300` 的透明 Button，
  `onMouseUpAddPat`：
  - 空槽 -> `Navigator.flow(FIGHT_PET_LIST)`，`data={ttype:2}`；
  - 有宠物 -> `CommandManager.CHOOSE_REST_PET_KEY(45)`，`{index,ttype:2}`。
- 45 服务端现在只会清 `pets.squad_slot`（PvE 出战槽），**不是擂台防守快照**。
- `FightPetListUI` 无论 `ttype` 是 1 还是 2，都发 42 列表 + 44 选择；
  44 服务端也只写 `squad_slot`。
- `CommandManager` 已有 `CHOOSE_ARENA_PET_LIST_KEY=43`，但服务端没有实现 43，
  `FightPetListUI` 也没用它。
- 结论：擂台宠物点击要真正编辑防守，必须新增防守页/命令，不能复用 45/44 的 PvE 语义。

### 2.3 已有服务端能力（T16b）

- `player_loadouts(kind='arena_defense')` 已存 3 件装备 + 2 只宠物实例 id。
- 515 读防守（无快照回退 PvE，`is_default=1`）。
- 516 保存防守（校验归属/槽位）。
- 37 `action=off&slot=1/2/3` 只卸该槽。
- 22 目前没有 `slot` 过滤；背包装备页还是全部装备。

## 三、目标交互

| 页面 | 点人物 | 点宠物槽 | 点已穿装备 |
|---|---|---|---|
| 人物面板 / PvE | 打开 PvE 装备配置 | 42/44/45 改 PvE 出战 | 先 37 off，再开该部位筛选 |
| 擂台防守页 | 打开防守装备配置 | 防守宠物选择，写 516 | 先 516 清该槽，再开筛选 |
| 擂台对手页 RingUI | 不接玩家编辑 | 不接玩家编辑 | 不接 |

“全局一致”指手势一致，不是数据同一套。

## 四、补丁拆分

### P1 命令常量（CommandManager）

新增（本地提议，先确认不冲突）：

```as3
public static var ARENA_DEFENSE_INFO_KEY:int = 515;
public static var ARENA_DEFENSE_SAVE_KEY:int = 516;
```

515/516 已在 `_SHOW_HANDLERS` 里实现。若客户端常量不能加，先用字符串 `515` 直发。

### P2 新增 `ArenaDefenseUI`

最小可行：复制 `HunterTaskUI` 的布局（中央 `Player` + 左右 `Pet` + 返回），
去掉狩猎/抓捕按钮，改成：

- `request()` -> `CommandManager.send(515,{})`
- `readDatas(515, param2)`：
  - `_player.data = {name, level, skin}`（防守快照的 `img`/`lv` 由 515 返回；
    第一版 515 还没返回 `img`，可先用 `GameUtil.skin`，后续补）
  - `_pet1/_pet2.data` 用 `param2.pets[0/1]`；
  - 底部加“保存防守”按钮（可选，第一版可改一只就立即 516）。
- 点宠物：
  - 空槽 -> `flow(FIGHT_PET_LIST)`，`data={ttype:3}`（新类型=防守）；
  - 有宠物 -> 发 516，把该槽置 0（需要 516 支持单槽更新，或先读 515 再回写两只）。
- 点中央人物 -> 打开 `RoleInfoUI` 的 `arena_defense` 模式（P3）。

> `FightPetListUI` 需要按 `ttype==3` 发 `CHOOSE_ARENA_PET_LIST_KEY(43)` 或
> 仍发 42 列表、44 选择但带 `ttype=3`；服务端 44 收到 `ttype=3` 时写防守快照，
> 不写 `squad_slot`。这样不用新 UI 也能复用选宠页。

### P3 RoleInfoUI 增加模式与装备热区

1. 增加 `private var _mode:String = "pve";`
2. `set data` 或 `readDatas` 接受 `mode="arena_defense"`：
   - `pve`：请求 510/2（现有）；
   - `arena_defense`：请求 515，读防守装备/宠物。
3. `initButton()` 末尾叠加三个透明 Button：
   - 位置按 `_info_txt` 的三行装备文本算：`x=30, width=250`，
     `y=90 + 行号 * 行高`；行高取 `GameUtil.fontsize0 + leading`，桌面截图再微调。
   - `name="1"/"2"/"3"` 对应武器/衣服/帽子。
   - 点击：
     - 有装备：`pve` -> 37 `action=off&slot=n`；`arena_defense` -> 516 该槽清 0；
     - 然后 `Navigator.flow(HOME_BAG_LIST)`，`data={ttype:3, slot:n, target:0}`。
4. `BagListUI` 的 22 请求带 `slot`；服务端按 `equip.txt type` 过滤（P5）。
5. 选中装备 -> 现有 39 详情 -> 37 穿上（PvE）或 516 写入（防守）。
   - 37 只改 `inventory.equipped`，防守模式不能用 37；防守必须走 516。

### P4 RingUI 只加“防守阵容”按钮

- `initButton()` 增加一个 `Button`（美术可用 `img_ring_top` 或纯文字），
  放在积分排名下方/左侧空位；`mouseUp` -> `Navigator.flow(ARENA_DEFENSE)`。
- 不改 `_player.mouseEnabled`，不改两侧宠物按钮。
- 新增 `Navigator.ARENA_DEFENSE` 常量与 `showCurrentItem(new ArenaDefenseUI())` 分支。

### P5 服务端补 22 的槽位过滤 + 44/45 的 ttype=3

22：

```text
showId=22&ttype=3&slot=1&p=1&n=9
```

- `slot` 1/2/3 时只返回 `equip.txt type` 对应的装备；不传时保持现状。
- 过滤后分页仍按过滤后的总数算。

44/45：

- `ttype=3`（防守）：
  - 44 把宠物写入 `player_loadouts(kind='arena_defense')` 的第一个空 pet 槽；
  - 45 从防守快照清掉该宠物；
  - **不写** `pets.squad_slot`。
- `ttype=1/2` 保持现有 PvE 语义。

43：可先只做 42 的别名；`FightPetListUI` 仍用 42 列表即可。

## 五、补丁脚本与重建

1. 用 FFDec 导出干净基线（`build/input-remote/APetHunter.swf`）。
2. 新补丁脚本按现有格式：
   - `client/air51-repack/patch_arena_defense_ui.py`：新增 `ArenaDefenseUI.as`；
   - `patch_roleinfo_equip_click.py`：RoleInfoUI 加模式 + 三个热区；
   - `patch_ring_defense_button.py`：RingUI 加按钮；
   - `patch_bag_slot_filter.py`：BagListUI 的 22 带 slot；
   - `patch_fightpet_ttype3.py`：FightPetListUI 的 44 带 ttype=3。
3. 所有 anchor 必须 `count == 1`，否则 `SystemExit`。
4. 重建顺序：先删 `build/input-explore/step-*.swf`，再跑
   `python rebuild-client-patches.py`；不要跨 worktree 复制 build。
5. 桌面：`dev-desktop.ps1 -Label c1 -Port 8081`，窗口 640×960；
   截图归档到 `docs/preview/2026-10-25/c1-*`。

## 六、验收清单

UI lane 逐条签字（`docs/design/ui-review.md`）：

1. 人物面板点武器/衣服/帽子：有装备先卸下，再开该部位筛选；空槽直接开筛选。
2. 选一件装备 -> 39 详情 -> 37 穿上，面板立即刷新；只影响该槽。
3. PvE 页面换宠：42/44/45 只改 `squad_slot`；6/74/103 战斗跟同一队。
4. 擂台防守页：点宠物 -> 选宠 -> 保存后 515 读到新队伍；PvE 换宠不影响防守。
5. 擂台防守页换装：只改 `player_loadouts`；PvE 面板装备不变。
6. 点“同步当前 PvE”后，防守才变成当前 PvE。
7. RingUI 对手页：中央人物/两侧宠物点击不改变玩家队伍（或明确只读）。
8. 截图：PvE 换装前/后、防守换装前/后、点已穿装备卸下前后、等级不够/错误提示。

## 七、风险

- **RoleInfoUI 装备行热区**依赖文本行高；不同字号/语言可能偏。先用桌面截图量，
  不要按 1080×2412 写坐标（逻辑 540×1206）。
- **506 语义**：本计划不把对手页改成玩家队伍；如果用户坚持，需要单独改标题/数据，
  并重做 506 的 `name/lv/skin`。
- **44/45 ttype=3** 会同时影响 `FightPetListUI` 的现有调用；必须保留 ttype=1/2 分支。
- **防守快照数值**按当前实例实时重算；精炼/升级会改变防守强度，若用户要冻结，
  再加 `snapshot_json`。
- 客户端没有真实 PvP，防守页做完也只是“配置 + 展示”，不要伪造战报。
