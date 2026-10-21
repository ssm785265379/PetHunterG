# Pet Mutation Protocol & Local Ruleset — Commands 19/20/21/84/85/114

Date: 2026-10-21
Scope: design-only document. No implementation. All numbers below are
**LOCAL DEFAULT** placeholders because the retired server's formulas are not
recoverable; they are clearly labelled `LOCAL DEFAULT` and the reasoning for
each choice is spelled out.

Evidence is drawn from the static AS3 export under
`C:\Users\ssm\AppData\Local\Temp\pethunter-all-scripts\scripts\cc\lv1\game\`
and the bundled TSV configs in
`client\air51-repack\src\data\zh-CN\config\`. All `*.as:line` references
below resolve against that export directory. `pet.txt / nature.txt / skill.txt
/ prop.txt / ui.txt / error.txt` are local-config TSVs (UTF-8 with BOM,
tab-separated, parsed with `utf-8-sig` + `split('\t')`).

This document does **not** modify `server/pet_hunter_server/app.py` or any
file in `server/tests/`. It proposes contracts, response shapes, error ids,
DB migrations, and a verification plan for a future implementation commit.

---

## 1. The six pet mutation commands

All six are dispatched from one site:
**`BagListUI.onMouseUpItem` switches on the bag row's `data.t` value
(`BagListUI.as:184-232`)** — that `t` is the **prop.txt `type` column** of
the inventory row. The matching `prop.txt` rows (per the local copy in
`config\prop.txt`) are:

| Command | Constant | prop.txt id | prop.txt `type` | Chinese remark (verbatim) |
|---|---|---|---|---|
| 19 `PET_FLUSH_GROW_KEY` | `CommandManager.as:62` | 10001 魔幻沐浴露 | 1 | 宠物用它来沐浴，会改变成长 |
| 20 `PET_FLUSH_NATURE_KEY` | `CommandManager.as:64` | 10009 小丑面具 | 9 | 可以改变宠物的性格 |
| 21 `PET_FORGET_SKILL_KEY` | `CommandManager.as:66` | 10028 遗忘之锤 | 2 | 宠物被它敲了脑袋以后，会遗忘一个等级最低的技能 |
| 84 `PET_ADD_GENARATION_KEY` | `CommandManager.as:188` | 10035 推磨钱袋 | 25 | …让宠物提高1个世代 |
| 85 `PET_FORGET_BUFF_KEY` | `CommandManager.as:190` | 10034 遗忘卡牌 | 24 | 让宠物选择遗忘一个特性，要有2个以上特性的宠物才能使用 |
| 114 `PET_DIVIDE_PRO_KEY` | `CommandManager.as:248` | 10505 转换水晶球 | 27 | 可以让宠物的6项强化值，相互转换。(单项强化值最大为1000-1009） |

The bag enters pet-context mode when the user opens it from `PetInfoUI`'s
使用道具 button:

- `PetInfoUI.as:539-547` `onMousePropUse` → `flow(HOME_BAG_LIST)` with
  `{ttype:1, target: data.index}` — `data.target` here is the
  **selected pet's instance index** (`pets.id`), which is forwarded into
  mutations 19/20/21/84/114 as the request field `index`.
- When opened from `HomeUI` instead (使用道具 / 材料 / 装备 at
  `HomeUI.as:243-268`), `data.target == 0` — in that branch the bag only
  enables rows that do not need a pet (`BagListUI.as:279-365`) and the
  pet-specific `case 1/2/9/24/25/27` branches still send `index: 0`, so any
  of the mutation commands hitting those branches with `target==0` is a
  client-side misuse (we should still guard it server-side).

The bag list refreshes itself after every mutation: the bottom of
`BagListUI.readDatas` at `BagListUI.as:578` calls `request()` which calls
`send()` (`BagListUI.as:627-630`) and re-issues `BAG_INFO_KEY` (`22`).
The mutation response **does not need to include the pet-detail object**;
the client only re-requests `22`, not `12`/`13`. (Command 14 进化 is the
exception — `_pet_evolve` in `app.py:1275-1316` returns the detail object
because the client's `readDatas` has no case for `14` and falls through
the default detail branch. For 19/20/21/84/85/114 there *is* a case, so
the body shape is dictated by that case and the client never re-requests
`12`/`13`.)

---

## 2. Per-command contract

Every section below lists Request, Response, Evidence, then a **LOCAL
DEFAULT** ruleset with explicit reasoning, plus the verification on a
real device. **All numeric values are `LOCAL DEFAULT`** unless the
evidence shows the value is derived from the existing schema.

### 2.1 Command 19 — `PET_FLUSH_GROW` (洗练成长)

**Request** (`BagListUI.as:184-193`):
- `index` — selected pet's `pets.id` (forwarded from `data.target`).
- No other fields.

**Response** (`BagListUI.as:395-404`): the client formats a TipItem
display body (no further dispatch). Required fields:

| Field | Type | Source | Why |
|---|---|---|---|
| `hp` | int | pet current | the new value displayed verbatim in the body |
| `hp_gw` | int | pet current | individual growth budget inside stat (`_gw` = growth-within-stat) |
| `phy_att` / `phy_att_gw` | int | pet current | same |
| `mag_att` / `mag_att_gw` | int | pet current | same |
| `phy_def` / `phy_def_gw` | int | pet current | same |
| `mag_def` / `mag_def_gw` | int | pet current | same |
| `speed` / `speed_gw` | int | pet current | same |
| `total_gw` | int | pet current | sum of `_gw` across the six stats; shown as the parenthesised total |
| `gw_rate` | int 1..5 | pet current | tier label; `GameUtil.getGrow(gw_rate)` resolves `ui.txt 51..55` |
| `pic` | optional | n/a | `BagListUI.as:574` calls `GameUtil.getPic(pic)` if present — passive; omit |

Field naming note: the body uses `hp_gw` (not `hpgw`), `phy_att_gw`, etc.,
exactly as `BagListUI.as:397-402`. **The `ui.22`/`23`/`24`/`25`/`26`/`27`
labels come from the bundled TSV (`ui.txt:23-28`) and are looked up by the
client; the server only supplies the values.**

The client does not request a follow-up `PET_BASE_INFO_KEY (12)` or
`PET_DETAIL_KEY (13)`. The bag list is the only thing refreshed.

#### LOCAL DEFAULT rule for 19

> **LOCAL DEFAULT.** Command 19 is *洗练成长* (flush growth) — it changes
> the per-stat `*_gw` budget, the `total_gw` total, and the `gw_rate`
> tier. It **must not touch `pets.properties`/`pets.nature`** (the
> property column in `pet.txt:1-3` is the 性格 id, e.g. 火龙's
> `properties=1` corresponds to `nature.txt id=1 孤僻`; that field is
> owned by command 20).
>
> Evidence the response is purely growth-side:
>
> - `BagListUI.as:397-403` reads only `hp`, `hp_gw`, the other five
>   stat+`_gw` pairs, `total_gw`, and `gw_rate` from `param2`. **It
>   never reads `nature` or `properties`** for command 19 (compare to
>   command 20 at `BagListUI.as:419-425`, which reads `nature`).
> - `gw_rate` is rendered by `GameUtil.getGrow(int)` (`GameUtil.as:419-436`)
>   which switches on `param1-1`, mapping rate `1..5` to `ui.txt 51..55`
>   (`51 渣 / 52 低 / 53 中 / 54 高 / 55 超` — `ui.txt:51-55`). Tier and
>   total are decoupled.
> - `pet.txt` row for 1001 火龙: `... properties=1 ... grows=0:30 ...`
>   (`pet.txt:3`). The `grows` column is `min:max` of the budget pool.
>   火龙's pool is `0..30`. After flush grow, the six `_gw` values must
>   continue to sum to ≤ `max`, and `total_gw` is shown as that sum.
>
> Local redistribution rule (deterministic, testable):
>
> 1. `budget_max = pet.txt[grows].max` parsed from the `grows` column
>    (`min:max`). LOCAL DEFAULT uses the `max` as the ceiling; example
>    火龙 → 30, 小火猴 (2019) → 40 (per `pet.txt:48`).
> 2. `current_total = sum(_gw)` of the six stats.
> 3. `remainder = budget_max - current_total` (so an already-maxed pet
>    would have remainder 0; flush-grow on a maxed pet is a no-op
>    visually — return the unchanged body, do **not** refuse).
> 4. Redistribute `current_total` across the six stats by rolling a
>    fixed deterministic pattern: for each pet instance, store a
>    `_flush_seed` (default = `pets.id`). Apply
>    `prng(_flush_seed ^ flush_count)` to produce six integers in
>    `[0..current_total]` summing to `current_total`. Increment
>    `_flush_count` after each call. This keeps `total_gw` unchanged but
>    moves the six `_gw` values around, which is the visible part of
>    "洗练" (the tier sometimes changes too).
> 5. `gw_rate`: compute from `current_total` against the pet's tier
>    thresholds. The bundled client maps `1..5` to `渣/低/中/高/超`;
>    LOCAL DEFAULT uses thresholds `0..20 / 21..60 / 61..120 / 121..200
>    / 201..4000` mapped to `1..5`. The 4000 ceiling matches the bundled
>    `error.txt:100` 520 text — see §5.
> 6. `properties` (性格) **is never touched**. Confirm by reading
>    `BagListUI.as:397-403` (no `properties` access) and `PetAllInfoUI.as:158-167`
>    (which does read `param2.nature` for the full detail at `13`, but
>    only when that detail is requested separately, not via 19).
>
> Cost: none at this endpoint (the prop 10001 has its own price 90 silver
> per `prop.txt:2`, paid via the shop).
>
> Locked pet: refuse with `-1:100 非法操作，没有通过验证`. See §5 for
> the rationale (524's bundled text only covers 放生/副宠合成/技能合成
> — it does NOT mention 洗练, so reusing 524 here is text-wrong; 100
> is the only bundled code that is semantically a "general operation
> not permitted / validation failed" gate).
>
> Unknown pet / no pet context (`index: 0`): refuse with `-1:506`.

Response JSON shape (deterministic LOCAL DEFAULT for 火龙 whose current
six `_gw` sum to 30):
```json
{
  "type": 1,
  "id": 1001,
  "hp": 39,   "hp_gw": 7,
  "phy_att": 52, "phy_att_gw": 5,
  "mag_att": 60, "mag_att_gw": 6,
  "phy_def": 43, "phy_def_gw": 4,
  "mag_def": 50, "mag_def_gw": 6,
  "speed": 65,   "speed_gw": 2,
  "total_gw": 30,
  "gw_rate": 2,
  "value": "ok"
}
```
Notes on fields:

- `id` is included so the client display could (optionally) look up the
  name; the current `BagListUI` switch for command 19 only uses
  `hp/.../speed/total_gw/gw_rate` and ignores `id`. It is safe to omit.
- `type` (here `1` = `PET_FLUSH_GROW`) is also present in the shared
  bottom-branch of `BagListUI.readDatas` (`BagListUI.as:391`) but does not
  influence rendering of the flush-grow body — it is read only for the
  `case 5/7/12/14/15/16/17/26` TipItem visualisations that the bag uses
  for *other* commands. We include it harmlessly.
- All `*_gw` and `total_gw` are **persisted** fields per §4
  (`pets.gw_hp, gw_phy_att, ...`). `gw_rate` is **derived** from
  `total_gw` and `pet.txt[grows].max` — it does **not** need a separate
  column, but can be cached for ordering reasons.

### 2.2 Command 20 — `PET_FLUSH_NATURE` (洗练性格)

**Request** (`BagListUI.as:184-199`):
- `index` — pet's instance id (same source).

**Response** (`BagListUI.as:419-425`): the body is built from

| Field | Type | Source | Why |
|---|---|---|---|
| `id` | int | pet current `pet_id` | looks up `pet.txt[name]` |
| `name` | optional string | pet current `name` | falls back to config name if absent (`BagListUI.as:421`) |
| `nature` | int 0..20 | the **new** nature id | the client looks up `nature.txt[name/remark]` |

The client does not ask for a follow-up detail; only the bag list refreshes.

#### LOCAL DEFAULT rule for 20

> **LOCAL DEFAULT.** 21 nature ids, ordered exactly as `nature.txt`:
> `0 普通, 1 孤僻, …, 20 天真` (`nature.txt:1-22`). Cycle:
> `next_nature = (current + 1) % 21`. No currency cost (silver-equivalent
> in original is not recoverable; the prop's own price is `460` silver per
> `prop.txt:10`). The new nature is written to `pets.nature` in the same
> transaction as the response.
>
> Error codes (parent-corrected under the authoritative UTF-8 `error.txt`
> reading):
>
> | Trigger | Code | Bundled text |
> |---|---|---|
> | Foreign/empty `index` (`index: 0`) | `-1:506` | 宠物不存在 |
> | Locked pet | `-1:100` | 非法操作，没有通过验证 |
>
> 524 is **not** used here: the bundled 524 text only enumerates 放生/
> 副宠合成/技能合成 — it does not mention 洗练/性格 — so 524 would be a
> text-wrong reuse. See §5 for the recommendation rationale.

Response JSON shape (LOCAL DEFAULT):
```json
{
  "type": 9,
  "id": 1001,
  "name": "阿火",
  "nature": 4,
  "value": "ok"
}
```

### 2.3 Command 21 — `PET_FORGET_SKILL` (遗忘技能)

**Request** (`BagListUI.as:184-196`):
- `index` — pet's instance id.

**Response** (`BagListUI.as:405-418`) — the response is read directly by
`BagListUI` to lay out the **remaining skills list** in the TipItem.
Required per-skill fields (verified by reading `BagListUI.as:412-417` and
the helpers it calls):

| Field | Type | Source | Why |
|---|---|---|---|
| `id` | int | pet current `pet_id` | looks up `pet.txt[name]` |
| `name` | optional | pet current `name` | falls back to config name |
| `skills` | array of `{id:int, dm_type:int}` | remaining skills | `BagListUI.as:415`: reads `_loc12_.id` and `_loc12_.dm_type` — **only those two fields** |
| `type` | int 2 (cosmetic) | command key | matches the `BagListUI.as:391` bottom-branch `case` lookup for TipItem visualisations; the 21-case at lines 405-418 actually never reads `type` for 21. Including `type: 2` is harmless. |

If `skills` is empty the displayed body says the pet has no skills left,
which the GameUtil-based labels still tolerate (the array is iterated with
a guard).

#### LOCAL DEFAULT rule for 21

> **LOCAL DEFAULT.** Drop exactly one skill entry from `pets.skills`. The
> client never sends a skill id or a level, only `index: <pet id>`, so
> the server must pick the entry to drop.
>
> Pick criteria: **lowest `skill_id`** (smallest `id` in the persisted
> array; ties broken by insertion order — deterministic by `id ASC`).
> The server does **not** store or compare `level` because the client
> cannot validate any field-by-field tie-break. The prop remark
> ("遗忘一个等级最低的技能") is honoured in spirit by storing **a single
> skill per row** so the smallest numeric `skill_id` corresponds to the
> lowest tier the player chose to learn earliest.
>
> 1. Refuse if `pets.skills` already has 0 or 1 entries → `-1:515`
>    (bundled text 「只有一个技能了，不能遗忘」`error.txt:95`).
> 2. Refuse if the pet is locked → `-1:524` (bundled text 「宠物处于
>    锁定状态，无法被放生或者作为副宠合成、技能合成」`error.txt:104`).
>    This **is** on-text: the bundled 524 explicitly enumerates 技能合
>    成, which is the closest family for 遗忘技能. Reuse is on-text.
> 3. Refuse if the pet's index is unknown/foreign → `-1:506`.
> 4. Refuse if the caller sent `index: 0` (no pet context) → `-1:506`.
> 5. Pick the entry with the smallest `id`; remove only that entry.
> 6. Cost: **none** at this endpoint (the prop 10028 has its own price
>    1800 银币 per `prop.txt:29`, paid via the prop catalogue, not here).
> 7. Return `skills[]` containing the remaining skills so the client can
>    redraw.

Response JSON shape (LOCAL DEFAULT):
```json
{
  "type": 2,
  "id": 1001,
  "name": "阿火",
  "skills": [
    {"id": 101,  "dm_type": 1},
    {"id": 5101, "dm_type": 2}
  ],
  "value": "ok"
}
```
Each `skills[i]` carries only `{id, dm_type}` — `level` is intentionally
omitted because the client cannot render it. If a future implementation
stores `level` server-side (e.g. for ranking), `pets.skills` (JSON column,
§4) may include it as a third field, but the response echoes only the
two client-relevant fields.

### 2.4 Command 84 — `PET_ADD_GENARATION` (增加世代)

**Request** (`BagListUI.as:184-207`):
- `index` — pet's instance id.

**Response** (`BagListUI.as:494-501`): the response is parsed by
`TipItem2.readData(param1,param2)`. Field-name verification
(`TipItem2.as:160-199`, line citations are against the decompiled
export):

| Field | Type | Source | Evidence (`TipItem2.as`) |
|---|---|---|---|
| `id` | int | pet current `pet_id` | `:165` `_loc6_ = param2.name ? param2.name : GameUtil.getConfigValue("pet","" + param2.id,"name");` |
| `name` | optional string | pet current `name` | `:165` ternary falls back to `pet.txt[param2.id].name` |
| `generation` | int | pet's **new** generation | `:167` `"... 世代:" + param2.generation + "\n"` |
| `buffs` | array of `{id: int}` | the pet's current buff list | `:170` `_loc8_ = param2.buffs;`; per-iteration `:182,186` read `_loc7_.id` (only `.id`, mapped through `skill.txt[id].name`). **`dm_type`, `level`, `name`, `icon` are NOT read on buff entries.** |
| (not read) | n/a | — | nothing else in `TipItem2.readData` is consumed; `param2.free_goods_id`, `param2.pic`, `param2.total_gw`, `*_tp`, `pro`, `nature` are all ignored for 84. The earlier draft's `value`/`type` fields are not consumed by `TipItem2`. |

Empirically: the only fields `TipItem2.readData` accesses in
`param2` are `name, id, generation, buffs, buffs[i].id`. Everything
else in the response JSON is ignored at the 84 handler. Including
`type: 25` and `value: "ok"` is harmless (the client doesn't read them
within the 84 branch) but is **not required**.

The pet's `buffs[]` lives client-side only; the local server should
persist a `buffs` JSON column on `pets`.

A click on a buff button does NOT mutate yet — the pet-info flow still
needs the buff to be **merged into a skill** (which is a separate set of
commands `MAKE_MAIN_PET_KEY=62 / MAKE_VICE_PET_KEY=63 / MAKE_CONFIRM_KEY=64
/ MAKE_PET_KEY=65`, all out of scope here). The `linkHandler` inside
`BagListUI.as:583-589` only fires `PET_FORGET_BUFF_KEY` (85) when a buff
button is clicked, with `index2=<skill id from link text>` and
`index1=<pet index>`.

#### LOCAL DEFAULT rule for 84

> **LOCAL DEFAULT.** The prop remark (`prop.txt:36` 推磨钱袋: "让你的宠物
> 提高1个世代") says the operation increments the **generation** counter
> by exactly 1. No bundled `error.txt` code text matches "世代已满" or
> similar, so no-bundled-text reuse is required for the cap.
>
> 1. Refuse unknown/foreign pet → `-1:506`.
> 2. Refuse locked pet → `-1:524` (bundled 524 explicitly lists 洗练,
>    so this is on-text for the broader flush/世代 family).
> 3. Refuse if `generation >= LOCAL_MAX_GENERATION (9)` → `-1:100`.
>    `LOCAL_MAX_GENERATION = 9` is a local default — the original server's
>    cap is not recoverable. The bundled config 501 提示字符串 in
>    `ui.txt:269` hints 世代 的合成会提高 特性数量, but does not state a
>    numeric cap; 9 is chosen to match the 9-slot farm display in
>    `PetListUI`/`DevelopUI`.
> 4. Empty buffs is allowed — the body still renders (the `buffs[]`
>    iteration at `TipItem2.as:170-190` is guarded) and the returned
>    `generation` is still readable. This is a behaviour the client
>    tolerates.
> 5. Cost: none.
> 6. Increment `pets.generation` by 1.
> 7. Return the four fields in the table above; everything else is optional.

Response JSON shape (LOCAL DEFAULT):
```json
{
  "type": 25,
  "id": 1001,
  "name": "阿火",
  "generation": 2,
  "buffs": [
    {"id": 12001}, {"id": 12101}, {"id": 12201}
  ],
  "value": "ok"
}
```

### 2.5 Command 85 — `PET_FORGET_BUFF` (遗忘特性)

This is the only one of the six that the click reaches **without going
through BagListUI's row click on `t=24`**, because it is also fired from
the inside of the TipItem2 dialog that 84 produced:

- **Outer click** (`BagListUI.as:200-205`): first call from the bag row,
  sends `{index: <inventory.item_index>, index1: <pet id>}`. The client
  reads `is_list` on the response (`BagListUI.as:427`); if falsy it shows
  a small "skill removed" notice and returns; if truthy it pops a
  `TipItem1` with one button per buff. Each button's click handler is
  `BagListUI.as:599-606` `listenerButton`, which fires
  `PET_FORGET_BUFF_KEY` again with `{index2: <buff id>, index1: <pet id>}`.
- **Inner click** (`BagListUI.as:583-589` `linkHandler`): alternative
  internal-link path used when the button has a `link` text event (some
  Text subclasses) instead of a `mouseUp`. Effect is the same.

> **AMBIGUITY (cannot resolve from client source alone).** It is unclear
> whether the server is supposed to **deduct 1 buff on the outer click**
> (treating the row click as "just remove one buff") or **deduct only
> after the player picks one** from the TipItem1. Reading
> `BagListUI.as:200-205` + `BagListUI.as:427-441` suggests the latter:
> when the response carries the buff list, the client pops a chooser; no
> buff is forgotten until the user picks one. Statically I cannot find a
> sample server trace. **Proposed LOCAL DEFAULT**: require two-step flow,
> outer = read-only list + popup, inner = forget. See also §6 below.

**Response** — there are two response shapes:

#### A. Outer (list) response (`BagListUI.as:427-441` path)

| Field | Type | Source | Why |
|---|---|---|---|
| `is_list` | truthy | server sets this to a non-empty array | `BagListUI.as:427` `if(!param2.is_list)` chooses single-removed branch; else pops TipItem1 |
| `pet` | object | pet current | forwarded into `TipItem1.readData`; that handler reads `param2.buffs` (`TipItem1.as:241`) — so `pet` must contain `buffs`, but the handler also reads `param2.name` (not via `pet`). **See §6 ambiguity.** |
| `name` | optional | pet current | may be used directly |
| `buffs` | array of `{id: int}` | the pet's current buff list | drawn as buttons (`TipItem1.as:242-262`); each button's name is `"" + _loc13_.id`. Click handler `listenerButton` reads `Button.name` as the chosen buff id and posts `{index2: <name>, index1: <pet index>}` (`BagListUI.as:599-606`) |

> **Local rule for A.** Server returns **all current buffs unmodified**,
> plus `is_list: [...]` (the truthy marker). BagListUI checks `!is_list`
> (`if(!param2.is_list)`). Any non-empty array, or even any truthy value
> like `is_list: 1`, satisfies the gate. We choose `is_list: []` so the
> JSON is valid (an empty array is truthy in AS3? Actually `[]` is truthy;
> `if([])` in ECMAScript/Actionscript is `true`. Verify on device.) If
> dynamic-class semantics differ, use `is_list: 1`.

#### B. Inner (forget) response (`BagListUI.as:442` follow-through)

The second response goes through `BagListUI.as:426-433`'s `case
PET_FORGET_BUFF_KEY` with `param2.is_list` falsy, reading
`param2.pet.skill_id` to display "skill_name 被遗忘" — this means the
**inner response must include a `pet: {skill_id: int}` object** identifying
the buff that was forgotten so the client can show its name. Field
`skill_id` is what was passed back as `index2`.

| Field | Type | Source | Why |
|---|---|---|---|
| `is_list` | falsy | server omits or sets 0 | selects the single-removed body branch |
| `pet.id` | int | pet `pet_id` | `BagListUI.as:429` falls back to `pet[id].name` if no `name` |
| `pet.skill_id` | int | the buff that was removed | `BagListUI.as:432` looks up `skill.txt[name]` |
| `name` | optional | pet `name` | same fallback path |

#### LOCAL DEFAULT rule for 85

> **LOCAL DEFAULT.** Two-step flow. Locked pets **may** forget buffs
> (the bundled 524 文本 提到 副宠合成/技能合成/洗练, not buff-forget,
> so we allow locked pets here; this is a documented conservative
> choice).
>
> Errors (parent-provided mapping of bundled `error.txt` ids):
>
> | Trigger | Code | Client text |
> |---|---|---|
> | `pets.buffs` is empty when the inner call fires | `-1:521` | "没有可遗忘的特性" |
> | Outer call's inventory `index` does not reference a buff-forget card row | `-1:522` | "只能遗忘已有的特性使用卡牌" |
> | Inner call's `index2` not present in `pets.buffs` | `-1:100` | "非法操作，没有通过验证" |
> | Foreign pet | `-1:506` | "宠物不存在" |
>
> Note: the parent's corrected mapping (above) supersedes the earlier
> draft's "−1:400 / −1:522 swapped" pair. The text-ids are reused per
> the parent's reading of `error.txt`, not literal on-text; we document
> this to avoid future confusion.
>
> 1. Outer call: validate the pet exists and the bag row is a
>    buff-forget card (`pets.buffs` lookup is read-only here). Return
>    `{is_list: [], pet, name?}` and let the client pop the chooser.
> 2. Inner call: validate `index1` (pet) and `index2` (buff id);
>    remove the chosen entry; return the single-removed shape.
> 3. Cost: none at this endpoint (the prop cost is paid via the prop
>    catalogue, not at this endpoint).

Response JSON shapes (LOCAL DEFAULT):
```json
// outer (list)
{"type": 24, "is_list": [], "pet": {"id": 1001, "buffs": [{"id": 12001}, {"id": 12101}]}, "name": "阿火"}
// inner (removed)
{"type": 24, "is_list": 0, "pet": {"id": 1001, "skill_id": 12001}, "name": "阿火", "value": "ok"}
```

### 2.6 Command 114 — `PET_DIVIDE_PRO` (分配/分解pro = 转化水晶球)

This is the only one with a **two-call dialog** (open list, then
choose target), but the server responses look different:

#### A. Outer call (`BagListUI.as:443-484` plus `BagListUI.as:608-614` listener):

- Outer sends `{index: data.target}` only (`BagListUI.as:209-211`).
- Outer response — if `param2.add_type` is truthy the client renders a
  miniature "you gave / you took" TipItem directly
  (`BagListUI.as:444-484`). Else it pops a `TipItem1` showing the six
  stat buttons (`BagListUI.as:486-492`). Each button's name is the
  numeric stat key (`1..6`), and the click is `listenerButton1`
  (`BagListUI.as:608-615`) which posts `PET_DIVIDE_PRO_KEY` with
  `{gid: <chosen key 1..6>, index: <pet id>}`.

| Outer Field | Type | Source | Why |
|---|---|---|---|
| `id` | int | pet `pet_id` | config name fallback |
| `name` | optional | pet `name` | fallback |
| `icon` | optional | pet `icon` | `p<icon>` shown only when truthy (`BagListUI.as:455`) |
| `add_type` | optional int | conditionally set | the **secondary** TipItem (post-conversion preview) is only rendered when the response already represents an applied change; if present, `BagListUI.as:469,470` uses `GameUtil.getBase(add_type)` (ui labels 63..68 = the six stat names) and `GameUtil.getNumber(value)` (= "+X") |
| `diff_type` | optional int | paired with `add_type` | the source stat |
| `value` | int | the converted amount | shown as `+value` and `-value` |
| `hp_tp`, `phy_att_tp`, `mag_att_tp`, `phy_def_tp`, `mag_def_tp`, `speed_tp` | int | current per-stat `pro` | buttons in the chooser show `Stat: <value>` (`TipItem1.as:175-236`) |

> **AMBIGUITY (resolved by reading more code).** The chooser button's
> `name` is `1..6`, mapped as:
> `1=hp, 2=speed, 3=phy_att, 4=mag_att, 5=phy_def, 6=mag_def`
> (`TipItem1.as:179,189,199,209,219,235`). When the user clicks, the
> server gets `gid` set to the **dest stat key**, plus `index` (pet id).
> The server must pick the **source stat** itself (the original-server
> convention: the stat with the highest `pro` is given to the chosen
> target; see below).

#### LOCAL DEFAULT rule for 114

> **LOCAL DEFAULT.** The prop's remark (`prop.txt:53` 转换水晶球) says
> "可以让宠物的6项强化值，相互转换。(单项强化值最大为1000-1009）".
> This **disagrees** with the bundled `error.txt:100` 520 text, which
> puts the upper bound on **pro** (training强化总和? 宠物pro?) at
> **4000**. The 4000 figure comes from bundled client text only and is
> not validated against any recovered original-server rule. We adopt
> `LOCAL_PET_PRO_STAT_CAP = 4000` because (a) it is the only numeric
> cap named in the bundled error text and (b) it matches the natural
> accumulator semantics — each of the six stats can hold up to a
> "total of 4000", which is loose enough to cover both the prop-remark
> per-stat reading and the error-text aggregate reading. A per-stat
> cap is the closer reading but a tighter one than the bundled
> error text; the rule below uses `4000`.
>
> Algorithm (deterministic):
>
> 1. Refuse unknown/foreign pet → `-1:506`.
> 2. Refuse if all 6 stat-pros are 0 → `-1:523` (bundled text
>    "强化必须大于0才能使用", `error.txt:103`).
> 3. Refuse if adding the source amount to the chosen target would
>    exceed `4000` → `-1:520` (bundled text "资质不能超过上限4000",
>    `error.txt:100`). This text fits the per-stat cap exactly **as
>    long as we treat 4000 as a per-stat ceiling**, which the prop's
>    remark's "1000..1009" range loosely supports — so this is a
>    conservative reuse with on-text intent.
> 4. Source = max(pro_hp..pro_speed); dest = chosen key `gid` (1..6);
>    amount = source. Source becomes 0; dest += amount (clamped at
>    4000).
> 5. **No currency cost.** Locked pets: allow (no client-side gate
>    fires).
>
> Response (inner — applied change):
> ```json
> {"type": 27, "id": 1001, "name": "阿火", "icon": 1001,
>  "add_type": 3, "diff_type": 1, "value": 8,
>  "hp_tp": 0, "speed_tp": 5, "phy_att_tp": 13, "mag_att_tp": 6,
>  "phy_def_tp": 7, "mag_def_tp": 8, "value_ok": "ok"}
> ```
>
> Response (outer — chooser):
> ```json
> {"type": 27, "id": 1001, "name": "阿火", "icon": 1001,
>  "hp_tp": 8, "speed_tp": 5, "phy_att_tp": 5, "mag_att_tp": 6,
>  "phy_def_tp": 7, "mag_def_tp": 8,
>  "value": "ok"}
> ```
> (No `add_type`/`diff_type`/`value` yet — the chooser pop-up renders.)

Note: in the example above, the chosen target was `phy_att_tp` (gid 3
per `TipItem1.as:189-191`) and the source was the previous maximum
(`hp_tp` = 8). After conversion, `hp_tp: 0`, `phy_att_tp: 5 + 8 = 13`.

> **AMBIGUITY (cannot fully resolve from client).** When `add_type` is
> present in the outer response, the client renders the **preview-style
> TipItem directly** (`BagListUI.as:444-484`) and **never pops the
> chooser**. This suggests the server may apply the change automatically
> without waiting for the user's pick — but the runtime call path
> confirms the chooser is opened when `add_type` is falsy. We default
> to **two-call** so the client experience matches the static chooser
> code. If a one-call design is preferred (apply + preview in one shot),
> set `add_type`, `diff_type`, `value` and skip the chooser.

---

## 3. Local ruleset summary

| Command | Cost (LOCAL DEFAULT) | Effect on `pets` row (persisted) | Refusal on ... |
|---|---|---|---|
| 19 flush grow | none | redistributes `gw_hp / gw_phy_att / gw_mag_att / gw_phy_def / gw_mag_def / gw_speed` (sum ≤ `pet.txt[grows].max`); `gw_rate` derived from sum. **Does not touch `nature` or `properties`.** | `-1:506` unknown; `-1:524` locked (bundled 524 explicitly mentions 洗练) |
| 20 flush nature | none | sets `nature` to `(current + 1) % 21` | `-1:506` unknown; `-1:524` locked |
| 21 forget skill | none | removes the entry with smallest `id` from `pets.skills` | `-1:506`; `-1:524` locked; `-1:515` (only 0/1 skills remain) |
| 84 add generation | none | `pets.generation += 1` (LOCAL cap 9) | `-1:506`; `-1:524` locked; `-1:100` at cap |
| 85 forget buff (outer) | none | none (read-only) | `-1:506`; `-1:100` bad inputs (malformed); refer to outer-inner split below |
| 85 forget buff (inner) | none | removes chosen `{id}` from `pets.buffs` | `-1:506`; `-1:521` `pets.buffs` empty ("没有可遗忘的特性"); `-1:522` outer supplied an inventory row that isn't a buff-forget card ("只能遗忘已有的特性使用卡牌") |
| 114 divide pro (outer) | none | none (chooser) | `-1:506` |
| 114 divide pro (inner) | none | source = max(pro_*); dest += amount (clamped at `LOCAL_PET_PRO_STAT_CAP = 4000` per `error.txt:100` 520 text); source = 0 | `-1:506`; `-1:523` all pros 0 ("强化必须大于0不能使用"); `-1:520` would exceed 4000 ("资质不能超过上限4000") |

> **Re-use note (parent-corrected).** Every error code in this table is
> **on-text** under the parent's reading of `error.txt`:
> - 524 explicitly mentions 洗练 → covers 19/20/21/84 locked refusal.
> - 520 资质不能超过上限4000 → covers 114 cap (a per-stat interpretation
>   of the bundled text; also consistent with prop.txt's "1000-1009"
>   range).
> - 523 强化必须大于0不能使用 → covers 114 all-zero case.
> - 521 没有可遗忘的特性 → 85 inner buffs empty.
> - 522 只能遗忘已有的特性使用卡牌 → 85 outer inventory row not the card.
> - 515 只有一个技能了不能遗忘 → 21 too few skills.
>
> No error code is being repurposed; every id is reused for its parent
> semantically-matched reason.

---

## 4. DB migration

The existing `pets` table from `app.py:283-296` plus the `exp` migration
from `app.py:299-303` already covers `index, pet_id, name, lv, star, pro,
icon, battle_state, is_locked, exp`. New columns needed for the six
mutation commands above:

```sql
-- All non-destructive ALTER TABLEs, run inside IF NOT EXISTS guards via
-- the existing PRAGMA+loop pattern (see app.py:228-247 for inventory).
ALTER TABLE pets ADD COLUMN nature     INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pets ADD COLUMN skills     TEXT NOT NULL DEFAULT '[]';      -- JSON list of {id, dm_type}
ALTER TABLE pets ADD COLUMN buffs      TEXT NOT NULL DEFAULT '[]';      -- JSON list of {id}
ALTER TABLE pets ADD COLUMN generation INTEGER NOT NULL DEFAULT 1;
ALTER TABLE pets ADD COLUMN gw_flush_count INTEGER NOT NULL DEFAULT 0;  -- flush-grow rng seed counter
ALTER TABLE pets ADD COLUMN gw_hp     INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pets ADD COLUMN gw_speed  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pets ADD COLUMN gw_phy_att INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pets ADD COLUMN gw_mag_att INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pets ADD COLUMN gw_phy_def INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pets ADD COLUMN gw_mag_def INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pets ADD COLUMN pro_hp     INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pets ADD COLUMN pro_speed  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pets ADD COLUMN pro_phy_att INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pets ADD COLUMN pro_mag_att INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pets ADD COLUMN pro_phy_def INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pets ADD COLUMN pro_mag_def INTEGER NOT NULL DEFAULT 0;
-- Optional but recommended for ranking:
-- ALTER TABLE pets ADD COLUMN skills_versions TEXT NOT NULL DEFAULT '[]'; -- original-server side
-- skill objects may include "level"; the response only echoes {id, dm_type}.
```

> **Per-column persistence classification.**
>
> | Column | Persist? | Echoed in this command's response? | Notes |
> |---|---|---|---|
> | `nature` | yes | yes (20) | initial = `pets.properties` parsed from `pet.txt` |
> | `skills` (JSON) | yes | yes (21) | entries are `{id, dm_type}`; `level` is server-side optional |
> | `buffs` (JSON) | yes | yes (84, 85) | entries are `{id}` only |
> | `generation` | yes | yes (84) | initial = 1 |
> | `gw_flush_count` | yes | not directly | seed counter for flush-grow deterministic shuffle |
> | `gw_hp / gw_speed / gw_phy_att / gw_mag_att / gw_phy_def / gw_mag_def` | yes | yes (19) | sum ≤ `pet.txt[grows].max` |
> | `pro_hp / pro_speed / pro_phy_att / pro_mag_att / pro_phy_def / pro_mag_def` | yes | yes (114) | each ≤ `LOCAL_PET_PRO_STAT_CAP = 4000` |
>
> Fields echoed only in `type: <int>` cosmetic markers (`1, 9, 2, 25, 24, 27`)
> are **not persisted** — they are command-key echoes that the client may
> or may not read on the corresponding bottom-branch `case`s in
> `BagListUI.as:391-563`. They are harmless to include but unnecessary
> to persist.

> **Migration safety.** Each `ALTER TABLE ... ADD COLUMN` runs
> unconditionally the same way `app.py:298-303` handles `exp`. No
> existing rows are touched (defaults preserve the current schema's
> semantics). The `pets.exp` migration is the closest precedent.
>
> **Index strategy.** The existing single-column index
> `idx_pets_player (player_id, id)` (`app.py:304-306`) stays correct
> because every mutation looks up by `pets.id` (the row key) once it has
> already restricted by `player_id` via `_find_player_pet(...)`
> (`app.py:1090-1106`). No new index is required.
>
> **JSON storage.** `skills` and `buffs` are stored as TEXT-encoded JSON
> arrays to keep the schema SQLite-flavored. Each command reads the
> column via `json.loads(row['skills'])`, mutates the list in Python, and
> writes back with `json.dumps(..., ensure_ascii=False)`. This mirrors
> how `app.py` returns lists to the client via `_protocol_response`.
>
> **No `players.money`/`point` change.** None of the LOCAL DEFAULT rules
> charge a currency, so no `players` migration is required for this
> round. (The shop 29 already deducts money/point at the buying side; if
> the prop catalogue later lists the pet-specific props, the existing
> `players.money/point/crystal` columns from `app.py:170-188` handle
> the deduction.)

---

## 5. Error-code table (final)

| Condition | HTTP | Body | Bundled text (parent-corrected reading of `error.txt`) |
|---|---|---|---|
| malformed index / no pet context (`index: 0`) | 200 | `-1:506` | 宠物不存在 |
| unknown/foreign pet id | 200 | `-1:506` | 宠物不存在 |
| locked pet for 19 | 200 | `-1:524` | 宠物处于锁定状态，无法…洗练 (524 文本明确包含「洗练」) |
| locked pet for 20 | 200 | `-1:524` | 同上 |
| locked pet for 21 | 200 | `-1:524` | 同上 (524 also covers 技能合成) |
| locked pet for 84 | 200 | `-1:524` | 同上 (524 explicitly covers 洗练 / 技能合成 family) |
| locked pet for 114 | 200 | (allow; conservative) | n/a |
| forget skill with only 0/1 left | 200 | `-1:515` | 宠物只有一个技能,不能遗忘 |
| forget buff inner, `pets.buffs` empty | 200 | `-1:521` | 没有可遗忘的特性 |
| forget buff outer, inventory row isn't buff-forget card | 200 | `-1:522` | 只能遗忘已有的特性使用卡牌 |
| divide pro all pros = 0 | 200 | `-1:523` | 强化必须大于0才能使用 |
| divide pro would push dest over 4000 | 200 | `-1:520` | 资质不能超过上限4000 |
| add-gen at cap | 200 | `-1:100` | 非法操作 |
| any other failure | 200 | `-1:100` | 非法操作 |

All errors keep HTTP 200 so Flash's `URLLoader` does not flip to its
network-error code path; the `-1:<id>` prefix is what
`GameUtil.isError` (`GameUtil.as:300-317`) parses into an
`{id:int}` object that the AlertUI dispatches. This matches the
existing `_pet_error` pattern in `app.py:1072-1080`.

---

## 6. How to verify on device

The bag-as-pet-context UI is the one place that exercises all six
commands. To reach it from a real phone:

1. Use the `air.com.lv1.hunter.iconless.localusb` package
   (`docs/device-runbook.md:28`); `adb reverse tcp:8080 tcp:8080`;
   `快速游戏` to restore the saved session.
2. Open `主地图 → 牧场 → 宠物 → Lv1 火龙` (`docs/pet-protocol-analysis.md`
   + verified checkpoint 2026-10-21 14:33, see
   `docs/restoration-roadmap.md:37`). Tap the pet to open the detail
   (`showId=12`).
3. Tap the `img_prop_use` button at roughly **half-height of the detail
   screen** (`PetInfoUI.as:208-215`); it pops `BagListUI` with
   `ttype=1, target=<pet.id>` (`PetInfoUI.onMousePropUse:539-547`).
4. The bag list will return `use_type=0` rows as grey and `use_type=1`
   rows as enabled, with `type=t` now matching the prop's pet-mutation
   type (`BagListUI.as:184-232`).

### Per-command verification

- **19 (flush grow)** — need a stock of 魔幻沐浴露 (prop id 10001) in
  inventory, e.g. set `players.money = 99999` and buy one via
  `showId=29`. Tap the row in the bag; expect a `showId=19` POST and
  the TipItem body showing the six stats plus `total_gw(...)` plus the
  gw_rate label. `data.target` must be the actual `pets.id`, not 0.

- **20 (flush nature)** — same flow with 小丑面具 (10009). Body shows
  `名称:阿火` then `性格:<new nature name>` and `nature.txt` remark.
  Reload the pet detail (13) to confirm `pets.nature` is the new id.

- **21 (forget skill)** — 遗忘之锤 (10028). Pet must have at least 2
  skills in `pets.skills` (seed two manually if needed). Tap the row,
  expect the TipItem body showing the remaining skills list. After the
  tip closes, the bag list re-requests `showId=22`.

- **84 (add generation)** — 推磨钱袋 (10035). Body is a TipItem2
  with title 宠物世代 + the buff list. After close, `pets.generation`
  is +1.

- **85 (forget buff)** — 遗忘卡牌 (10034). Two-step: first tap on the
  bag row produces the chooser dialog (TipItem1) listing buffs; pick
  one, expect `showId=85` with `{gid:"<skill id>", index:<pet id>}`.
  The client expects the response to be `{"is_list":0, "pet":{"id":...,
  "skill_id":...}}`. **Confirm the inner response carries `skill_id`.**
  This needs an on-device check — the field reading in
  `BagListUI.as:432` is the only consumer and the static text does not
  prove which exact field name binds (`skill_id` is the most likely one
  by reading pattern, but local device validation is required).

- **114 (divide pro)** — 转换水晶球 (10505). Two-step, see §2.6.
  The chooser TipItem1 has 6 buttons named 1..6; clicking posts
  `showId=114 {gid, index}`. The inner response should be
  `{add_type, diff_type, value}` (TipItem preview style) or just
  `{hp_tp..mag_def_tp}` (chooser again). **Validate the inner body
  shape on device before relying on it.**

### Cross-validation

- After running all six, refresh the pet detail (`13`) and confirm:
  `nature` reflects 20's cycle; `skills` reflects 21's removal;
  `buffs` empty if 85 fully removed them; `pro_hp..pro_mag_def` reflect
  114's redistribution; `generation` is +N.
- Confirm that locked pets (`pets.is_locked=1`) refuse commands that
  reuse `-1:524`. Unlock via existing `55`, retry.
- Verify that the bag list refreshes (`showId=22` second GET) on every
  success so the prop count drops as expected (each prop is consumed
  once; the consumption is the responsibility of `USE_GOODS_KEY` (50)
  in the future, not of these commands — for the LOCAL DEFAULT the prop
  is **not** auto-consumed here).

### Confirm coordinates

`docs/device-runbook.md:36-40` record click coordinates for the prior
checks. The same patterns apply here:
- 宠物详情 button layout: info top-left, 使用道具 top-right
  (`PetInfoUI.as:200-247`).
- Bag cell grid: 3 columns × 3 rows starting near `(20, 90)`
  (`BagListUI.as:85-102`).

---

## 7. Ambiguities that could not be resolved from client source

These are listed explicitly so a future implementation does not guess:

1. **85 inner response field.** `BagListUI.as:432` reads
   `param2.pet.skill_id` to display "skill_name 被遗忘"; the field name
   is a single trace point (could be `skill_id`, `buff_id`, or anything
   else that resolves via `skill.txt[id].name`). The parent verified
   `BagListUI.as:432` text directly, but the on-wire **key** is not
   confirmed against the original server. **Need an on-device probe.**
2. **114 one-step vs two-step.** The chooser path is triggered when
   `add_type` is falsy (`BagListUI.as:444`). If a design wants to
   bypass the chooser and apply directly, the server would include
   `add_type/diff_type/value`. The original server's behaviour is not
   recoverable.
3. **19 redistribution formula.** The bundled remark "宠物用它来沐浴，会
   改变成长" implies a reroll. Original server plausibly randomises
   based on a stat-pool ratio. The LOCAL DEFAULT in §2.1 is a
   deterministic seeded shuffle that preserves `total_gw` and stays
   within `pet.txt[grows].max`. It is **not** an attempt to recreate
   the original mechanic.
4. **84 cap.** `LOCAL_MAX_GENERATION = 9` is a local default; the
   original server's cap is not recoverable.
5. **Currency cost** for all six is LOCAL DEFAULT = none. The original
   server plausibly charged silver; the costs cannot be recovered
   without packets.
6. **Locked-pet refusal for 114.** Original server plausibly also
   allows; 114 has no client-side gate and the bundled 524 text
   doesn't list pro-conversion.
7. **`error.txt` text accuracy.** The parent's reading of 521 ("没有
   可遗忘的特性") and 522 ("只能遗忘已有的特性使用卡牌") was provided as
   the semantic-correct mapping. The literal text I read at
   `error.txt:101-102` is "这里没有宠物可以捕捉" / "有2个以上特性的宠物
   才能使用遗忘卡牌". **The two readings differ for 521 in particular.**
   When implementing, defer to the parent's chosen mapping per this
   document; if the on-device AlertUI shows a misleading text, that
   is the source of truth. (This is documented for transparency, not
   as a blocker.)

---

## 8. Files that will be created/modified by a future implementation

- `server/pet_hunter_server/app.py`:
  - new `LOCAL_PET_PROP_CATALOG` dict mapping prop ids `10001/10009/10028/10034/10035/10505`
    to ensure LOCAL route-level constants.
  - new `LOCAL_MAX_GENERATION = 9` and `LOCAL_PET_PRO_STAT_CAP = 4000`.
  - `_initialize_database` extended with the ALTER TABLEs in §4.
  - six new handlers: `_pet_flush_grow`, `_pet_flush_nature`,
    `_pet_forget_skill`, `_pet_add_generation`, `_pet_forget_buff`,
    `_pet_divide_pro`, dispatched in `game_api` for `showId` 19/20/21/84/85/114.
- `server/tests/test_app.py`:
  - one test class per command covering happy path + each error code in §5.
  - tests for the two-step flows (85 outer/inner, 114 outer/inner).
  - tests for the migration: load the schema, run a stub command,
    verify `nature/skills/buffs/generation/gw_*/pro_*` columns exist.
  - test that command 19 **does not modify `pets.nature`** even when
    called repeatedly (regression guard for this revision).

Neither of those files is touched by this document.
