# Task System Protocol Design (46 / 47 / 501)

Scope: the task detail, reward-claim and task-list commands for the local
offline server. Every claim about client behaviour cites the decompiled AS3 at
`C:\Users\ssm\AppData\Local\Temp\pethunter-all-scripts\scripts` as
`file.as:line`. Config facts cite the bundled TSVs under
`client/air51-repack/src/data/zh-CN/config/`.

This is a **design**, not implemented code. `server/pet_hunter_server/app.py`
and `server/tests/` were not modified.

## 1. Transport envelope (shared with every other command)

| Fact | Evidence |
|---|---|
| Commands 46/47/501 are `default:` cases, i.e. `m=show&showId=<id>` | `CommandManager.as:311-312` (GET) and `CommandManager.as:385-388` (POST) |
| Default send is POST to `<GameUtil.url>flash.do`; `uid`, `v`, `t`, `sn` are always appended | `CommandManager.as:433-458`, `CommandManager.as:412-428` |
| Response envelope is `<cmdId>\t<json>` split on tab, first field is the command id, second is JSON | `APetHunter.as:143-146`, `APetHunter.as:161-162` |
| `-1:<int>` is recognised as a protocol error and turned into an `AlertUI` with `error.txt` text | `GameUtil.as:300-317`, `APetHunter.as:147-159` |

So an error is the bare body `-1:<errorId>` (no tab, no JSON) — exactly what
the existing `_pet_error()` helper already emits
(`server/pet_hunter_server/app.py:1072-1080`).

## 2. Per-command contract

### 2.1 Command 501 — `REQUEST_TASK_KEY`: declared but **never sent**

| Fact | Evidence |
|---|---|
| `REQUEST_TASK_KEY:int = 501` is defined | `CommandManager.as:250` |
| A repo-wide search of the exported AS3 for `REQUEST_TASK_KEY` returns **only that declaration** | grep over `scripts\` — no `CommandManager.send(REQUEST_TASK_KEY, ...)` anywhere |

**Conclusion: 501 is dead code in this client.** The task list is fetched by
**511**, not 501. 501 should either stay unimplemented (HTTP 501, current
behaviour) or be aliased to the same handler as 511 as a defensive measure;
aliasing costs nothing because no client path reaches it.

### 2.2 Command 511 — `REQUEST_TASK_LIST_KEY`: the real task list

| Fact | Evidence |
|---|---|
| `REQUEST_TASK_LIST_KEY:int = 511` | `CommandManager.as:264` |
| `TaskTrackUI.init()` calls `send()` immediately on construction; `send()` sends 511 with **no parameters** | `TaskTrackUI.as:18-26` |
| `MainUI` constructs `TaskTrackUI` as a permanent child of `MainUI` at x=50, y=180 | `MainUI.as:57-63` |
| `MainUI.request()` calls `_ui_task_track.request()` which re-sends 511 | `MainUI.as:334-348`, `TaskTrackUI.as:58-61` |
| 511 is routed to the tracker only (not to the open item UI) | `MainUI.as:84-86` |

Response fields consumed (`TaskTrackUI.as:28-56`):

| Field | Type | Use |
|---|---|---|
| `list` | array, required | iterated; `param2.list` is cast to `Array` and `.length` is read |
| `list[].id` | int | fed to `TaskItem.data.id`; also looked up in `task.txt` for the name |
| `list[].is_finish` | truthy | `TaskItem.update()` picks `img_t1` when truthy, else `img_t0` (`TaskItem.as:72-84`) |

The row name comes from `task.txt[name]`, not from the server
(`TaskTrackUI.as:48-53`), so **every id returned by 511 must exist in
`task.txt`** or the row renders with an empty label.

The tracker has **no paging** — it renders one 100px-tall `TaskItem` per row
starting at y=0 (`TaskTrackUI.as:45-47`). Returning an unbounded list would draw
a tall column, but it cannot crash.

### 2.3 Command 46 — `TASK_INFO_KEY`: task detail

Request: sent by `TaskItem.onMouseUp` with a **single field `gid`** equal to the
task id from 511 (`TaskItem.as:86-89`).

Response fields consumed by `TaskUI.readDatas` (`TaskUI.as:185-424`):

| Field | Type | Where read | Meaning |
|---|---|---|---|
| `id` | int, required | `TaskUI.as:200-201`, `:354` | task id; used for `task.txt[name]`, `[remark]`, `[needRemark]` lookups |
| `type` | int, required | `TaskUI.as:188`, `:203` | condition kind; selects the condition renderer |
| `icon` | int, required | `TaskUI.as:191` | NPC class name is built as `"n" + icon` and resolved via `ApplicationDomain.getDefinition` with **no try/catch** |
| `condition` | object or null, required | `TaskUI.as:206` etc. | progress; shape depends on `type` |
| `reward_money` | int | `TaskUI.as:368-377` | gold icon `img_gold_0` |
| `reward_point` | int | `TaskUI.as:358-367` | silver icon `img_silver_0` |
| `reward_crystal` | int | `TaskUI.as:378-387` | crystal icon `img_crystal_0` |
| `reward_goods` | array | `TaskUI.as:388-405` | each row `{id:int, num:int}`; `prop.txt[id].iconId` → class `p<iconId>` |
| `is_finish` | truthy | `TaskUI.as:420-423` | **the claim button visibility** (`img_task` button) |

Reward rendering is **truthiness-guarded**, not `> 0` guarded: `if(param2.reward_point)`
(`TaskUI.as:358`). Sending `0` is safe (falsy) but sending a **non-numeric
string** would render a junk `*<string>` label. Use integers.

`condition` shapes by `type` — every branch is a hard requirement:

| `type` | `condition` shape | Fields read | Icon source |
|---|---|---|---|
| 6 | object | `need_id`, `now_value`, `need_value` | `pic.txt[need_id].iconId` (`TaskUI.as:205-217`) |
| 7 | object with `list` array | each `{need_id, now_value, need_value}` | `pet.txt[need_id].iconId` (`TaskUI.as:218-242`) |
| 16 | object | `need_id`, `now_value`, `need_value` | hardcoded `img_icon_10` (`TaskUI.as:243-255`) |
| 18 | object | `need_id`, `now_value`, `need_value` | hardcoded `img_icon_11` (`TaskUI.as:256-268`) |
| 19, 3, 20 | object | `now_value`, `need_value` | hardcoded `img_gold_0` (`TaskUI.as:269-295`) |
| 4, 21 | object | `now_value`, `need_value` | hardcoded `img_silver_0` (`TaskUI.as:296-309`) |
| 5, 22 | object | `now_value`, `need_value` | hardcoded `img_crystal_0` (`TaskUI.as:310-323`) |
| 17, 23 | object with **`now_value` array** | each `{need_id, own_num, need_num}` | `prop.txt[need_id].iconId` (`TaskUI.as:324-346`) |
| default (incl. 0, 2, 8, 10, 11, 12, 14, 24) | **not read** | — | falls back to a text block printing `task.txt[needRemark]` (`TaskUI.as:347-355`) |

Note the asymmetry: for type 17/23 the **progress array is `condition.now_value`**
and each row uses `own_num`/`need_num`, not `now_value`/`need_value`. That is a
genuine quirk of the client, not a typo in this document.

Every `n<icon>` and `p<iconId>` class referenced above was verified to exist in
the bundled SWFs (decompressed scan of `client/air51-repack/**/*.swf`):
`n50001`-`n50005` in `npc.swf`; `p1001`/`p1002` in `pet2000.swf`;
`p20001`/`p20002`/`p20003` in `skin.swf`; `p10007`/`p10011`/`p10014`/`p11001`
in `prop.swf`; `img_task`, `img_t0`, `img_t1`, `img_box_task_1` resolve;
`img_icon_10`/`img_icon_11` in `icon.swf`.

**Routing**: on 46 the client does **not** stay on the tracker. `MainUI`
switches to the task screen and then immediately re-requests function flags
(`MainUI.as:87-91`):

```
case CommandManager.TASK_INFO_KEY:
   Navigator.getInstance().flow(Navigator.GAME_TASK);
   Navigator.getInstance().item.readDatas(param1,param2);
   requestFunctionKey();          // -> CommandManager.send(502)
```

`GAME_TASK = 1050624` and it instantiates `TaskUI`
(`Navigator.as:50`, `Navigator.as:402-404`). **Every 46 response is followed by a
502 request** — so 502 must be implemented for the task screen to settle, or the
`Probar` spinner pushed by `CommandManager.send` (`CommandManager.as:457`) stays
up.

### 2.4 Command 47 — `TASK_REWARD_KEY`: claim

Request: `TaskUI.onMouseUp` sends `data`, which was set at `TaskUI.as:187-190`
during the 46 handler to exactly:
```json
{"ttype": "<the type field of the 46 response>", "gid": "<the id field of the 46 response>"}
```

So 47 carries **two fields, `ttype` and `gid`**, both echoed straight back from
the 46 response. The server must therefore persist or re-derive `type` for 46;
it cannot assume the client will send a trustworthy `ttype`.

Response handling (`TaskUI.as:425-433`):

| Step | Behaviour | Evidence |
|---|---|---|
| 1 | `SoundManager.play("sound_4")` | `TaskUI.as:427` |
| 2 | `Navigator.getInstance().flow(Navigator.CMD_BACK)` — leaves the task screen immediately | `TaskUI.as:428` |
| 3 | `if(param2.pic) GameUtil.getPic(param2.pic)` — `pic` is an **array** | `TaskUI.as:429-432` |

**The 47 response body is otherwise completely ignored.** No `value`, no
`reward_*`, no currency fields are read by `TaskUI`. The reward animation is
driven entirely by the optional `pic` array. This is corroborated by
`IllustrationTaskUI`, the structurally identical illustration-task screen, which
reads `reward_point/reward_money/reward_crystal/reward_goods` from **its** 49
response but again nothing else (`IllustrationTaskUI.as:267-345`).

`pic` entries are pushed into `GetPicItem`, which reads `id`, `icon`,
`reward_point`, `reward_crystal`, `reward_money`, `reward_goods[].id/num`
(`GameUtil.as:534-553`, `GetPicItem.as:148-264`). The name lookup is
`pic.txt` → `pet.txt` → `prop.txt` → `exploreEquip.txt`
(`GetPicItem.as:184-197`). Note `GetPicItem.as:222-232` has a **client bug**:
the `reward_money` branch prints `param1.reward_crystal`. A local server should
send `pic: []` or omit `pic` entirely for currency-only tasks to avoid showing a
wrong number.

**Does the client re-request 511 after claiming? Yes — indirectly.**

`TaskUI` calls `flow(Navigator.CMD_BACK)` from the `GAME_TASK` node. Per
`Navigator.as:922-927` the default back branch pops to the previous node, which
is `MAIN`; `show()` then takes the `current == MAIN` branch and calls
`con.request()` (`Navigator.as:317-328`). `MainUI.request()` calls
`_ui_task_track.request()` (`MainUI.as:344-347`) which re-sends 511
(`TaskTrackUI.as:58-61`). So claiming automatically refreshes the tracker — no
client-side 511 request needs to be synthesised by the server, but the 47
handler **must** commit the state change before the follow-up 511 lands, or the
row will still show as claimable.

### 2.5 Summary of fields the client reads

| Command | Request fields | Response fields read |
|---|---|---|
| 501 | — | — (never sent) |
| 511 | none | `list[].id`, `list[].is_finish` |
| 46 | `gid` | `id`, `type`, `icon`, `condition`, `reward_money`, `reward_point`, `reward_crystal`, `reward_goods[].{id,num}`, `is_finish` |
| 47 | `ttype`, `gid` | `pic` (array, optional; everything else ignored) |

## 3. The real task data model (`config/task.txt`)

UTF-8 with BOM, TAB separated, **1 header + 92 data rows**, 17 columns.
Verified header (`task.txt:1`):

```
id  iconId  name  needLevel  needDate  questId  type  value  team  divide
rewardMoney  rewardPoint  rewardCrystal  rewardGoods  needRemark  rewardRemark  remark
```

Real rows verbatim (`task.txt:2`, `:4`, `:14`, `:21`):

```
1    50001  新手指导     0  0  0    0   0    1  1  0     200  0     0         要求:无                        奖励:200银币    主人，喵喵村为猎人学员安排了新手指导…
4    50002  使用体力饮料 0  0  3    12  10007 1  1  0     0    0     11001:1   要求:使用体力饮料（家园→使用道具） 奖励:烈焰龙之玉*1  体验到图鉴奖励的惊喜了吧？…
13   50002  入会考试（三）0  0  12   10  1:100 1  1  0     500  0     0         要求:1地图完成度100%              奖励:500银币    啊哈，这套装备很适合你呢~…
101  50001  好友任务1    1  0  1002 2   3    2  2  0     1000 0     0         要求:点击好友按钮。               奖励:1000银币   在游戏里，好友越多，奖励就越多。…
```

### 3.1 Column semantics

| Column | Role | Evidence / data |
|---|---|---|
| `id` | task id, the `gid` of 46 and 47 | three distinct bands in the 92 rows: `1-19` tutorial, `101-1105` main/side, `1501-1510` and `2001`, `3001` repeatables |
| `iconId` | NPC portrait, returned as `icon`; class `n<iconId>` | values `50001`-`50005`, all present in `npc.swf` |
| `name` / `remark` | label + body text; **client-side lookups only** | `TaskUI.as:200-201`, `TaskTrackUI.as:48` |
| `needLevel` | minimum player level; `0` or `1` across all 92 rows | 19 rows at 0, 73 at 1 |
| `needDate` | day gate; **`0` for every one of the 92 rows** | no daily-reset semantics recoverable |
| `questId` | prerequisite task id: task X requires questId to be finished | `task 14` has `questId=13`; `task 4` has `questId=3` |
| `type` | condition kind (table in §3.2) | 15 distinct values |
| `value` | condition payload, `:`-separated | e.g. `20001:20004`, `1:100`, `11002:1` |
| `team` | category `1` tutorial / `2` main+side / `5` daily | 19 / 72 / 1 rows |
| `divide` | UI sub-tab grouping | values 1-8 and 11 |
| `rewardMoney` | → `reward_money`, gold | |
| `rewardPoint` | → `reward_point`, silver | |
| `rewardCrystal` | → `reward_crystal`, crystal | |
| `rewardGoods` | → `reward_goods`, `id:num` (`0` = none) | e.g. `11001:1`, `10011:3` |
| `needRemark` | the text shown by the `default` branch when `condition` is not read | |
| `rewardRemark` | cosmetic text, unused by `TaskUI` | |

### 3.2 The 15 condition types present in the data

Counts over all 92 rows, with one real example each:

| `type` | n | Example | `value` | Server can verify? |
|---|---|---|---|---|
| 0 | 4 | `1` 新手指导 | `0` | **YES** — no condition; auto-complete |
| 2 | 12 | `2` 入会考试（一） | `1` | **NO** — a UI-navigation click counter; nothing records clicks |
| 6 | 5 | `5` 打造烈焰之剑 | `20001:20004` | **PARTIAL** — target item id exists in `pic.txt`; but making (34) is unimplemented |
| 7 | 1 | `15` 我的牧场 | `1001` | **YES** — "own pet 1001" |
| 8 | 3 | `6` 装备烈焰之剑 | `20001:20004` | **YES** — `inventory.equipped = 1` for that item |
| 10 | 23 | `13` 入会考试（三） | `1:100` | **NO** — map completion %; hunting (4/6/7) unimplemented |
| 11 | 1 | `19` 宠物出战 | `0` | **YES** — `pets.battle_state != 0` |
| 12 | 3 | `4` 使用体力饮料 | `10007` | **PARTIAL** — `prop.txt[10007].type = 7`; cmd 50 implements it, but see §3.3 |
| 14 | 4 | `7` 入会考试（二） | `3` | **NO** — monster defeat; hunting unimplemented |
| 16 | 4 | `1101` 图鉴大师 | `820` | **NO** — illustration count; 48/49 unimplemented, `pic.txt` has no id 820 |
| 18 | 1 | `102` 好友任务2 | `2` | **NO** — friend count; cmd 51/52 unimplemented |
| 20 | 26 | `1501` 蓝色晶石1 | `3000` | **YES** — gold balance ≥ value |
| 21 | 1 | `1012` 合成实验室 | `2000` | **YES** — silver balance ≥ value |
| 23 | 3 | `1002` 物物交换 | `11002:1` | **PARTIAL** — `id:count`, goods trade (cmd 32-34) unimplemented |
| 24 | 1 | `3001` 绑定帐号 | `0` | **NO** — external account binding |

### 3.3 What the local server actually tracks

State that exists and is authoritative today:

- `players`: `lv`, `money`, `point`, `crystal`, `pet_capacity`, `bag_capacity`, `ht_ap`
- `pets`: `pet_id`, `lv`, `star`, `battle_state`, `is_locked`
- `inventory`: `item_id`, `quantity`, `equipped`

Implemented mutating commands: 14 (evolve), 15 (release), 18 (rename), 29
(buy), 37 (equip), 40 (expand pets), 50 (use item), 55 (lock), 69 (sell),
plus 27/28 read paths.

**Honest conclusion: types 0, 7, 8, 11, 20, 21 are fully evaluable today.**
Type 12 is evaluable only for props in `LOCAL_PROP_CATALOG` with a real effect
(10007 type 7, 10002/10011 type 5, 10014 type 14, 10022/10023 type 16/17) —
`prop.txt` lists 10011 宠物饼干 as `type=5` (pet exp +10000), but the local
`LOCAL_PROP_CATALOG` (`app.py:76-82`) does **not** include 10011, so
"used 宠物饼干" cannot be observed; and type 23 goods-trade cannot be observed
at all. Types 6 (crafting) and 23 are structurally parseable but have no
producing command.

## 4. Conditions that MUST stay unimplemented

Any type outside §4.1 would require the server to *invent* the player's
progress. Marking such a task complete would be fabricating success. They are
therefore **excluded from the seeded task set entirely** — they are not
"incomplete", they are not offered to the client at all.

Excluded types: **2, 6, 10, 12 (except 10007), 14, 16, 18, 23, 24**.

For each exclusion, the specific missing evidence:

| Type | What the server would have to assert | What is missing |
|---|---|---|
| 2 | "player clicked UI button X" | no click telemetry exists anywhere in the DB |
| 6 | "player crafted item Y" | cmd 34 GOODS_MAKE unimplemented; no craft log table |
| 10 | "map N is 100% complete" | no map/hunt tables; cmd 4/6 unimplemented |
| 12 | "player used prop Z" | no item-use log; only cmd 50 handlers exist and no counter is persisted. **Do not** infer from the stack shrinking — consumables are sold and traded too |
| 14 | "player defeated monster M" | no monster/battle tables; hunting unimplemented |
| 16 | "player owns N illustrations" | `pic.txt` has no id 820; illustration (48/49) unimplemented |
| 18 | "player has N friends" | cmd 51/52 unimplemented, no friends table |
| 23 | "player traded goods A for B" | no trade log; commands 32-34 unimplemented |
| 24 | "player bound an external account" | no binding state in the schema |

A safe alternative for a *repeatable* balance task (type 20/21) is a
**latch**: once satisfied, the task completes and the counter resets on claim.
That is honest because the balance really was observed. This is the basis of
the local ruleset below.

## 5. LOCAL RULESET

Everything in this section is an **invented local rule**, not a recovered
original-server rule. Each invented number is labelled **LOCAL DEFAULT**.

### 5.1 Assignment

1. **LOCAL DEFAULT** — Assignment is *lazy and level-based*, not chain-driven.
   A task becomes visible when `players.lv >= task.need_level`.
   Evidence for level gating: `task.txt` `needLevel` is the only non-zero
   prerequisite column (73 of 92 rows are `1`).
2. **LOCAL DEFAULT** — `questId` is honoured as a soft prerequisite: a task with
   `questId != 0` is only offered once that prerequisite is **claimed**. This
   is inferred from the data shape (`task 14` has `questId=13`), not from any
   client-side code; the client never reads `questId`.
3. **LOCAL DEFAULT** — The tracker shows **at most 6 tasks**, ordered by
   `team` then `id`. Rationale: `TaskTrackUI` renders every row 100px tall with
   no paging (`TaskTrackUI.as:45-47`), so an unbounded list overflows the
   screen. 6 rows = 600px, which fits the 180px offset on a 1080px-tall stage.
4. **LOCAL DEFAULT** — Claimed tasks leave the tracker. A task that becomes
   claimable after being hidden stays hidden until the 511 that follows the
   claim; the server re-evaluates the whole visible set on every 511.
5. **LOCAL DEFAULT** — The task set never refreshes daily. `needDate` is `0` for
   all 92 config rows, so there is no evidence for any reset cycle.

### 5.2 Completion evaluation

On every 511 and on every 46, the server recomputes `is_finish` from live state.
This guarantees the client never sees a stale or fabricated flag.

| Type | LOCAL rule | Evaluated from |
|---|---|---|
| 0 | always finished | — |
| 7 | finished when `now_value = count(pets where pet_id = need_id)`, `need_value = need_id` | `pets` |
| 8 | finished when an `inventory` row has `item_id = need_id AND equipped = 1`; `need_value = 1`, `now_value = 0 or 1` | `inventory.equipped` |
| 11 | finished when `count(pets where battle_state != 0) >= 1`; `need_value = 1` | `pets.battle_state` |
| 20 | finished when `players.money >= value`; `need_value = value`, `now_value = min(money, value)` | `players.money` |
| 21 | finished when `players.point >= value`; same clamping | `players.point` |

For type 8 the client never reads `condition` at all
(`TaskUI.as:296-309` handles 4/21; type 8 falls to the `default` text branch),
so `condition` for type 8 can be omitted. It is still sent for uniformity.

### 5.3 Rewards

**LOCAL DEFAULT** — Rewards are taken verbatim from the `task.txt` row: the
server does not rescale them. This keeps the client display and the DB in
agreement with the shipped Chinese text.

| Config column | Applied as |
|---|---|
| `rewardMoney` | `players.money += n` |
| `rewardPoint` | `players.point += n` |
| `rewardCrystal` | `players.crystal += n` |
| `rewardGoods` `id:num` | upsert into `inventory` with `team` from `prop.txt[team]`, `item_type`=`type`, `use_type`=`useType` — identical to the existing shop-buy upsert (`app.py:826-844`) |

**LOCAL DEFAULT** — The 47 response returns `{"value":"ok","pic":[]}`.
`pic` is an empty array, not omitted, because `GameUtil.getPic` is only called
when `param2.pic` is truthy and an empty array is falsy in AS3 — so the branch is
skipped cleanly and the client-side `reward_crystal` bug in
`GetPicItem.as:222-232` can never surface.

**LOCAL DEFAULT** — Claiming does **not** force a `510`/`2` refresh. The
on-screen currency icons are only refreshed by HomeUI (`HomeUI.as:194-196`) and
ShopInfoUI (`ShopInfoUI.as:406-408`); after a claim the user returns to the map,
where no currency readout is drawn. The DB is the source of truth and the next
`showId=2`/`showId=28` will show the new balance.

### 5.4 The seeded task set (all rows are real `task.txt` rows)

Only honestly-evaluable tasks are seeded. Ids, names, types, values and rewards
are copied exactly from `task.txt`.

| id | name | type | value | needLv | questId | rewards | why honest |
|---|---|---|---|---|---|---|---|
| 1 | 新手指导 | 0 | `0` | 0 | 0 | 200 point | no condition |
| 6 | 装备烈焰之剑 | 8 | `20001:20004` | 0 | 5 | 500 point | 37 sets `equipped`; 20001 is the local starter equip |
| 15 | 我的牧场 | 7 | `1001` | 0 | 14 | 500 point | 1001 is in `LOCAL_STARTER_PETS` |
| 19 | 宠物出战 | 11 | `0` | 0 | 18 | `10011:3` | `pets.battle_state` is a real column |
| 1012 | 合成实验室 | 21 | `2000` | 1 | 1011 | `10014:1` | `players.point` |
| 1501 | 蓝色晶石1 | 20 | `3000` | 1 | 1017 | `10032:60` | `players.money` |
| 1502 | 蓝色晶石2 | 20 | `5000` | 1 | 1501 | `10032:100` | `players.money` |

`needRemark` is non-empty only for task 1501 (`要求:` empty) and is unused by the
renderers for these types anyway.

### 5.5 Chain feasibility warning — a blocking ambiguity

The seeded set is **not reachable in order by a fresh local account**:

- Task 6 requires `questId=5` (打造烈焰之剑, type 6) — **excluded**, because
  crafting (cmd 34) is unimplemented. Under rule §5.1.2 task 6 would never be
  offered.
- Task 15 requires `questId=14` (成为猎人, type 0) — honest, but 14 itself
  requires `questId=13` (入会考试（三）, type 10) — **excluded**.

**LOCAL DEFAULT, chosen deliberately:** the `questId` gate is enforced only
between tasks that are themselves in the seeded set. Seeded tasks whose
`questId` points at an excluded task are treated as having no prerequisite, and
this is the one place the local server knowingly diverges from a plausible
original rule. It is called out here rather than hidden, because the alternative
— seeding the excluded prerequisites — would require fabricating progress.

The net effect: a brand-new local account sees tasks **1, 19** immediately (type 0
and type 11), and **6, 15, 1012, 1501, 1502** once `lv >= 1`. Level 1 is the
default for every local character, so in practice all seven are visible
immediately and 1 can be claimed straight away.

## 6. DB schema

```sql
-- Static task catalogue, seeded from config/task.txt at startup.
CREATE TABLE IF NOT EXISTS tasks (
    task_id       INTEGER PRIMARY KEY,   -- task.txt id
    icon_id       INTEGER NOT NULL,      -- task.txt iconId -> n<icon_id>
    name          TEXT    NOT NULL,      -- mirrored for logging only
    task_type     INTEGER NOT NULL,      -- task.txt type
    condition_value TEXT   NOT NULL,     -- task.txt value, raw ':' separated
    need_level    INTEGER NOT NULL DEFAULT 0,
    quest_id      INTEGER NOT NULL DEFAULT 0,
    team          INTEGER NOT NULL DEFAULT 1,
    reward_money    INTEGER NOT NULL DEFAULT 0,
    reward_point    INTEGER NOT NULL DEFAULT 0,
    reward_crystal  INTEGER NOT NULL DEFAULT 0,
    reward_goods    TEXT    NOT NULL DEFAULT '0'  -- task.txt rewardGoods raw
);

-- Per-player task state. One row per (player, task) that has been *offered*.
CREATE TABLE IF NOT EXISTS player_tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    task_id     INTEGER NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    is_claimed  INTEGER NOT NULL DEFAULT 0 CHECK (is_claimed IN (0,1)),
    claimed_at  TEXT,
    UNIQUE (player_id, task_id)
);
```

`is_finish` is **deliberately not stored** — it is recomputed on read so it can
never disagree with the live state described in §5.2.

### 6.1 Migration

Append to the existing `_initialize_database()` in
`server/pet_hunter_server/app.py`, after the `shop_goods` block. Use
`CREATE TABLE IF NOT EXISTS` in the same style as `inventory`
(`app.py:203-227`).

```sql
CREATE TABLE IF NOT EXISTS tasks (
    task_id         INTEGER PRIMARY KEY,
    icon_id         INTEGER NOT NULL,
    name            TEXT    NOT NULL,
    task_type       INTEGER NOT NULL,
    condition_value TEXT    NOT NULL,
    need_level      INTEGER NOT NULL DEFAULT 0,
    quest_id        INTEGER NOT NULL DEFAULT 0,
    team            INTEGER NOT NULL DEFAULT 1,
    reward_money    INTEGER NOT NULL DEFAULT 0,
    reward_point    INTEGER NOT NULL DEFAULT 0,
    reward_crystal  INTEGER NOT NULL DEFAULT 0,
    reward_goods    TEXT    NOT NULL DEFAULT '0'
);

CREATE TABLE IF NOT EXISTS player_tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id  INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    task_id    INTEGER NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    is_claimed INTEGER NOT NULL DEFAULT 0 CHECK (is_claimed IN (0, 1)),
    claimed_at TEXT,
    UNIQUE (player_id, task_id)
);
```

`tasks` is reference data, so seed it like `shop_goods`: delete and re-insert
on every start (`app.py:262-266` documents this pattern). `player_tasks` is
player data and must **never** be rewritten.

### 6.2 Seed rows

```sql
DELETE FROM tasks;

INSERT INTO tasks (task_id, icon_id, name, task_type, condition_value,
                   need_level, quest_id, team, reward_money, reward_point,
                   reward_crystal, reward_goods) VALUES
 (   1, 50001, '新手指导',     0, '0',          0,    0, 1,     0, 200,   0, '0'),
 (   6, 50001, '装备烈焰之剑', 8, '20001:20004',0,    5, 1,     0, 500,   0, '0'),
 (  15, 50005, '我的牧场',     7, '1001',       0,   14, 1,     0, 500,   0, '0'),
 (  19, 50005, '宠物出战',     11,'0',          0,   18, 1,     0,   0,   0, '10011:3'),
 (1012, 50005, '合成实验室',   21,'2000',       1, 1011, 2,     0,   0,   0, '10014:1'),
 (1501, 50003, '蓝色晶石1',    20,'3000',       1, 1017, 2,     0,   0,   0, '10032:60'),
 (1502, 50003, '蓝色晶石2',    20,'5000',       1, 1501, 2,     0,   0,   0, '10032:100');
```

Every value above is copied from `task.txt`; only the omission of the other 85
rows is a local choice. `10011` and `10014` must be added to
`LOCAL_PROP_CATALOG` so the reward upsert stores correct `item_type`/`use_type`;
if they are not added, the rows land with `0/0` and the client renders them
non-clickable in the bag (`BagListUI.as:225-231` sends `USE_GOODS` with
`index`/`index1`, and a zero `use_type` never enables the cell in
`BagListUI.as:293-349`).

### 6.3 Route wiring

Three new branches in `game_api()` (`app.py:1401-1452`), replacing the current
stub at `app.py:1450-1451`:

```python
if command == "show" and _request_value("showId") == "46":
    return _task_info(current_app.config["DATABASE"])
if command == "show" and _request_value("showId") == "47":
    return _task_reward(current_app.config["DATABASE"])
if command == "show" and _request_value("showId") == "511":
    return _task_list(current_app.config["DATABASE"])
```

501 needs no branch. It is unreachable from the client (§2.1).

## 7. Exact response JSON

### 7.1 Command 511 — `REQUEST_TASK_LIST_KEY`

Success (HTTP 200, `text/plain; charset=utf-8`):

```json
{"list":[{"id":1,"is_finish":1},{"id":6,"is_finish":0}]}
```

| Key | Type | Required | Notes |
|---|---|---|---|
| `list` | array | yes | may be empty; `TaskTrackUI.as:39-41` reads `.length` |
| `list[].id` | int | yes | must exist in `task.txt` or the label renders empty |
| `list[].is_finish` | int `0`/`1` | yes | truthiness only; `1` shows `img_t1` |

No error case is reachable: the client always sends 511 without parameters and
an empty/absent `list` renders an empty column.

### 7.2 Command 46 — `TASK_INFO_KEY`

Request fields: `gid` (int), `uid` (string, added by `CommandManager`).

Success:

```json
{"id":6,"type":8,"icon":50001,"condition":{},
 "reward_money":0,"reward_point":500,"reward_crystal":0,
 "reward_goods":[],"is_finish":1}
```

`reward_goods` is `[]` (never `0`) — `TaskUI.as:390-391` does
`int(_loc10_.length)`, and `null.length` would throw.

A type 7 example (the only multi-entry condition shape):

```json
{"id":15,"type":7,"icon":50005,
 "condition":{"list":[{"need_id":1001,"now_value":1,"need_value":1}]},
 "reward_money":0,"reward_point":500,"reward_crystal":0,
 "reward_goods":[],"is_finish":1}
```

A type 20 example (balance task, clamped progress):

```json
{"id":1501,"type":20,"icon":50003,
 "condition":{"now_value":3000,"need_value":3000},
 "reward_money":0,"reward_point":0,"reward_crystal":0,
 "reward_goods":[{"id":10032,"num":60}],"is_finish":1}
```

A type 21 example (silver):

```json
{"id":1012,"type":21,"icon":50005,
 "condition":{"now_value":2000,"need_value":2000},
 "reward_money":0,"reward_point":0,"reward_crystal":0,
 "reward_goods":[{"id":10014,"num":1}],"is_finish":1}
```

| Key | Type | Required | Notes |
|---|---|---|---|
| `id` | int | yes | echoes `gid` |
| `type` | int | yes | echoes `task_type`; also what the client sends back as `ttype` |
| `icon` | int | yes | `n<icon>` must exist or `TaskUI.as:191` throws |
| `condition` | object | yes | shape per §2.3; use `{}` for type 8 |
| `reward_money` | int | yes | `0` is safe (falsy guard at `TaskUI.as:368`) |
| `reward_point` | int | yes | |
| `reward_crystal` | int | yes | |
| `reward_goods` | array | yes | `[]` or `[{id,num}]`; `id` looked up in `prop.txt` |
| `is_finish` | int `0`/`1` | yes | drives the `img_task` claim button |

### 7.3 Command 47 — `TASK_REWARD_KEY`

Request fields: `uid`, `gid` (int), `ttype` (int, echoed `type` from the 46
response).

Success:

```json
{"value":"ok","pic":[]}
```

`pic: []` is falsy in AS3, so `GameUtil.getPic` is skipped
(`TaskUI.as:429-432`) and the client-side `reward_crystal` bug
(`GetPicItem.as:227`) never triggers. `value` is sent for log parity even
though `TaskUI` never reads it.

### 7.4 Error codes

`_pet_error()` emits `-1:<id>` with HTTP 200 by default
(`app.py:1072-1080`); `GameUtil.isError` parses it
(`GameUtil.as:300-317`) and `APetHunter.as:147-159` shows `error.txt[value]`.

| Situation | Error id | `error.txt` text | Why this id |
|---|---|---|---|
| Missing/blank `uid` | **100** | 非法操作，没有通过验证 | existing convention for every command (`app.py:647,700,745`) |
| Unknown `uid` (no such player) | **103** | 玩家不存在 | existing convention (`app.py:654,709,751`) |
| `gid` absent or non-integer | **100** | 非法操作，没有通过验证 | malformed input, same class as bad `index` |
| **Unknown task id** | **211** | 该任务已经完成 | **closest fit in the shipped table.** There is no "task does not exist" code. 211 is the only task-state error id present. Using 103 (玩家不存在) here would be actively wrong. **This is a LOCAL DEFAULT mapping — flagged, not recovered.** |
| **Locked / prerequisite not claimed** | **211** | 该任务已经完成 | same table gap; a locked task is "not claimable", and 211 is the only task-state message. **LOCAL DEFAULT.** |
| **Task not completed** | **107** | 点击左上角的"！？"完成任务，才能开放更多功能哦~ | the shipped text for an unfinished objective; it already gates five other screens (`GameUI.as:198,208,218,228,243`). **LOCAL DEFAULT.** |
| **Task already claimed** | **211** | 该任务已经完成 | the text is literally exact for this case |
| Bag full while granting `reward_goods` | **300** | 背包已满，不能此进行操作。 | real code (`error.txt:49`), and a real risk: `10014` raises `bag_capacity` |

**Known ambiguity — flag for the parent agent.** `error.txt` has no distinct
codes for "unknown task", "task locked", "task already claimed" or "task not
finished". It only has `211 该任务已经完成` (`error.txt:39`). Reusing 211 for
all three states is the least-wrong mapping, but it means a locked task and a
already-claimed task show the same dialog. If a better set of ids exists in a
non-`zh-CN` `error.txt` (the repack may carry more locales than the one bundled
here), those should be preferred instead.

### 7.5 Reward granting transaction

Inside one `with _connect_database(...)` block:

1. Re-evaluate `is_finish` from live state. If false → `-1:107`.
2. If already claimed → `-1:211`.
3. If `quest_id != 0` and the prerequisite is not claimed **and is in the
   seeded set** → `-1:211`.
4. If a `reward_goods` grant would exceed `bag_capacity` → `-1:300`.
5. Apply `money`/`point`/`crystal` increments and the `inventory` upsert using
   the same statement shape as the shop buy (`app.py:826-844`).
6. `INSERT OR IGNORE` / `UPDATE` the `player_tasks` row to `is_claimed = 1`,
   `claimed_at = <ISO timestamp>`.

Step 1 before step 2 matters: a repeated claim of an already-claimed
balance-latched task would otherwise pass the liveness check again.

## 8. Device verification plan

Preconditions from `docs/device-runbook.md`: Flask on `127.0.0.1:8080`,
`adb reverse tcp:8080 tcp:8080` active, package
`air.com.lv1.hunter.iconless.localusb`.

### Step A — 511 lists tasks

1. Launch, tap **快速游戏**. Expect `autoLogin` → `showId=510` → `showId=511`.
2. **Log**: `showId=511` HTTP 200, body `{"list":[...7 ids...]}`.
3. **Screen**: the task tracker column on the main map (x=50, y=180) shows 7
   `TaskItem` rows, each 100px apart, names rendered from `task.txt`:
   新手指导 / 装备烈焰之剑 / 我的牧场 / 宠物出战 / 合成实验室 / 蓝色晶石1 /
   蓝色晶石2. Task 1's row uses `img_t1` (finished) if the liveness rule for
   type 0 says finished, else `img_t0`.
4. **DB**:
   `SELECT task_id,is_claimed FROM player_tasks WHERE player_id=<id>;`
   → 7 rows, all `is_claimed=0`.

### Step B — 46 opens the task screen

1. Tap the **first** tracker row (~x 150, y 230 physical).
2. **Log**: `showId=46` with field `gid`, HTTP 200. Then **immediately**
   `showId=502` — this is mandatory (`MainUI.as:90`); if 502 is still 501 the
   spinner will not clear and this step must be blocked on 502.
3. **Screen**: `TaskUI` with 任务描述 (ui.txt 317), 完成条件 (318), 任务奖励
   (319); an NPC portrait at ~75% stage width (class `n50001`); task name and
   `remark` text; a silver icon showing `*500` for 装备烈焰之剑; the
   完成条件 area shows the `needRemark` text block (type 8 falls to the default
   branch).
4. **Negative check**: no `#1065` (`getDefinition` failure) and no crash. This
   proves `n50001` resolved.

### Step C — claim button visibility tracks liveness

1. For task 1 (type 0): the `img_task` button at the bottom right must be
   **visible** (`_btn_finish.visible = param2.is_finish`, `TaskUI.as:420-423`).
2. For task 1501 (type 20, needs `money >= 3000`): with the player's money
   below 3000 the button must be **hidden**. This is the key honesty check —
   the button state must follow the real `players.money` value.
3. Then set `UPDATE players SET money = 3000 WHERE uid=...`, re-enter the task,
   and confirm the button appears.

### Step D — claim with 47

1. On task 1, tap the claim button.
2. **Log**: `showId=47` with fields `gid,ttype`, HTTP 200, body
   `{"value":"ok","pic":[]}`.
3. **Screen**: the `Probar` clears, the task screen closes via `CMD_BACK`, and
   the main map reappears with the task tracker refreshed — this refresh is a
   **client-initiated** `showId=511`, and it should appear in the log within a
   second of the 47.
4. **DB**:
   - `player_tasks.is_claimed` 0→1 for task 1
   - `players.point` +200
5. Re-open task 1: the claim button must now be hidden.

### Step E — negative paths

| Action | Expected |
|---|---|
| Re-claim task 1 | log `showId=47`, HTTP 200, body `-1:211`, `AlertUI` with 该任务已经完成 |
| Claim task 1501 with money 0 | body `-1:107`, dialog about finishing the task first |
| POST `showId=46` with `gid=9999` (not in `tasks`) | body `-1:211` |
| POST `showId=47` with no `gid` | body `-1:100` |
| POST with an unknown `uid` | body `-1:103` |

### Step F — reward goods land correctly

1. Claim task 19 (宠物出战, `reward_goods` `10011:3`) after setting some pet's
   `battle_state = 1`.
2. **DB**: `SELECT item_id,quantity,team,item_type,use_type FROM inventory
   WHERE item_id=10011;` → `quantity=3`, `team=1`, and `item_type`/`use_type`
   taken from `prop.txt` (type 5, useType 2). If these two are `0`, the reward
   item renders but is not clickable in the bag — add 10011 to
   `LOCAL_PROP_CATALOG` per §6.2.

### Step G — type 7 and type 8 liveness end to end

1. Task 15 (type 7) completes automatically for a new account, because 1001 is
   a starter pet. Confirm `is_finish=1` on the very first fetch.
2. Task 6 (type 8) completes only after 37 sets `equipped=1` on item 20001.
   Claim it first — confirm the button is hidden — then 家园 → 装备 → 穿戴,
   re-enter the task, and confirm the button appears.

## 9. Open questions for the parent agent

1. **501**: confirmed dead code. Leave unimplemented, or alias to 511?
   Aliasing is zero-risk but adds a branch that no client path can reach.
2. **Error ids**: `error.txt` has no distinct codes for unknown / locked /
   not-finished tasks (§7.4). The design reuses 211 and 107. If another locale's
   `error.txt` is available it may carry better ids.
3. **`questId` gating**: the design only enforces prerequisites between seeded
   tasks, which means a seeded task whose prerequisite was excluded is offered
   early (§5.5). The alternative — seeding excluded prerequisites — would require
   fabricating completion.
4. **Type 12 / 10011**: 宠物饼干 is a real, in-bundle prop that would make a
   genuine "use a prop" task, but `LOCAL_PROP_CATALOG` does not implement it and
   cmd 50 does not log uses. Adding a use-log table would open this type up
   honestly; without one it stays excluded.
5. **502 (`REQUEST_FUNCTION_KEY`)**: 46 always triggers it (`MainUI.as:90`) and
   it is currently unimplemented, so the task screen cannot be verified on
   device until 502 returns at least `{"value":"0"}`.
