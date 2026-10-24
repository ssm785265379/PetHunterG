# 人物成长（等级/经验/称号/属性/装备技能）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 人物等级靠战斗经验自动涨；称号/转生 1-120 手动转职（读 `upRole` 的需求等级、降级、宝箱）；面板六维随等级/称号成长并与战斗共用一套数值；人物面板显示已穿装备自带的技能。

**架构：** `players` 增加 `exp/job`；`config_tables.up_role_table()` 按 `job` 读 120 行；`_grant_hero_exp` 负责经验与自动升级；`_role_stats(worn, lv, job)` 成为面板与战斗的唯一属性口径；70/71/72 实现列表/详情/转职。客户端不需要改包（转职界面和技能栏已存在）。

**技术栈：** Python 3.11 + Flask + SQLite，pytest。

**规格：** `docs/superpowers/specs/2026-10-24-bag-context-and-character-growth-design.md` 第四节。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `server/pet_hunter_server/config_tables.py` | `up_role_table()` 读取 120 级称号表 |
| `server/pet_hunter_server/app.py` | 数据列、经验/升级、属性口径、装备技能、70/71/72 |
| `server/tests/test_app.py` | 每个任务的失败测试 |
| `server/scripts/grant_hero_exp.py` | 本地维护脚本（跳级验证转职） |
| `docs/...` | 交接与验证记录 |

---

### 任务 1：读取 upRole 称号表

**文件：**
- 修改：`server/pet_hunter_server/config_tables.py`
- 测试：`server/tests/test_app.py`

- [ ] **步骤 1：写失败测试**

```python
def test_up_role_table_reads_all_hunter_titles():
    from pet_hunter_server import config_tables as tables

    rows = tables.up_role_table()
    assert len(rows) == 120
    assert rows[2]["needLevel"] == "400"
    assert rows[4]["lowerLevel"] == "999"
    assert rows[1]["rewardGoods"] == "0"
```

- [ ] **步骤 2：运行确认失败**

运行：`cd server; .\.venv\Scripts\python.exe -m pytest tests/test_app.py::test_up_role_table_reads_all_hunter_titles -q`
预期：FAIL（`AttributeError: module ... has no attribute 'up_role_table'`）。

- [ ] **步骤 3：实现 loader**

在 `config_tables.py` 末尾、`clear_caches()` 之前加入：

```python
@lru_cache(maxsize=1)
def up_role_table() -> dict[int, dict[str, str]]:
    """The 120 hunter titles from upRole.txt, keyed by `job` (not `id`)."""
    root = _config_root()
    if root is None:
        return {}
    path = root / "zh-CN" / "config" / "upRole.txt"
    if not path.is_file():
        return {}
    rows: dict[int, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            record = dict(zip(header, line.split("\t")))
            raw = record.get("job", "").strip()
            if raw.isdigit():
                rows[int(raw)] = record
    return rows
```

并在 `clear_caches()` 里加 `up_role_table.cache_clear()`（与其它 lru_cache 并列）。

- [ ] **步骤 4：运行确认通过**

运行：`pytest tests -q`
预期：全部 PASS。

- [ ] **步骤 5：Commit**

```bash
git add server/pet_hunter_server/config_tables.py server/tests/test_app.py
git commit -m "feat(人物): 读取 upRole 的 120 级称号表（按 job 键，含需求等级/降级/宝箱）"
```

---

### 任务 2：players.exp/job 与 510 面板

**文件：**
- 修改：`server/pet_hunter_server/app.py`
- 测试：`server/tests/test_app.py`

- [ ] **步骤 1：写失败测试**

```python
def test_player_payload_carries_real_job_and_exp(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "HeroJob")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE players SET lv=7, job=3, exp=123 WHERE uid=?", (uid,)
        )
        connection.commit()
    _, profile = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "510", "uid": uid}
    ))
    assert profile["lv"] == 7
    assert profile["job"] == 3
    assert profile["exp"] == 123
```

- [ ] **步骤 2：运行确认失败**

运行：`pytest tests/test_app.py::test_player_payload_carries_real_job_and_exp -q`
预期：FAIL（`job` 恒 1、没有 `exp`）。

- [ ] **步骤 3：加列与迁移**

在 players 的迁移区（`max_explore_ap` 之后）加：

```python
        if "exp" not in player_columns:
            connection.execute(
                "ALTER TABLE players ADD COLUMN exp INTEGER NOT NULL DEFAULT 0"
            )
        if "job" not in player_columns:
            connection.execute(
                "ALTER TABLE players ADD COLUMN job INTEGER NOT NULL DEFAULT 1"
            )
```

- [ ] **步骤 4：payload 用真实 job/exp**

`_PLAYER_ROW_SQL` 改为：

```python
_PLAYER_ROW_SQL = """
    SELECT id, nick AS name, lv, job, exp, sex, img, money, point, crystal,
           ht_ap, max_ht_ap, arena_ap, max_arena_ap
    FROM players WHERE uid = ?
"""
```

`_player_payload` 中删掉 `job=1` 的硬编码：

```python
    payload.update(
        guild_name="", guild_position=0, arena_rank=_local_arena_rank()
    )
```
（`job/exp` 已在 `dict(player)` 里。）

- [ ] **步骤 5：运行确认通过**

运行：`pytest tests -q`
预期：全部 PASS。

- [ ] **步骤 6：Commit**

```bash
git add server/pet_hunter_server/app.py server/tests/test_app.py
git commit -m "feat(人物): players 增加 exp/job，510 面板返回真实等级/称号/经验"
```

---

### 任务 3：人物经验曲线 + 自动升级 + 狩猎给经验

**文件：**
- 修改：`server/pet_hunter_server/app.py`
- 测试：`server/tests/test_app.py`

- [ ] **步骤 1：写失败测试**

```python
def test_hunt_grants_hero_exp_and_levels_the_hunter(tmp_path: Path, monkeypatch):
    from pet_hunter_server import app as A

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "HeroExp")
    baseline = A.hunter_exp_to_next(1)
    assert baseline == 100

    monkeypatch.setattr(A, "_record_is_win", lambda record: True)
    _envelope(client.post("/flash.do", data={
        "m": "show", "showId": "6", "uid": uid, "hid": 1, "ttype": 1,
    }))
    _, profile = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "510", "uid": uid}
    ))
    assert profile["lv"] > 1, "一场胜利的人物经验应足够升到 2 级"
    assert profile["exp"] >= 0
```

- [ ] **步骤 2：运行确认失败**

运行：`pytest tests/test_app.py::test_hunt_grants_hero_exp_and_levels_the_hunter -q`
预期：FAIL（`hunter_exp_to_next` 不存在 / lv 仍 1）。

- [ ] **步骤 3：实现曲线与升级**

在 `exp_to_next` 附近加：

```python
# 人物等级：1-1000，经验够了自动升；数值是 LOCAL DEFAULT，可单独调。
LOCAL_HERO_MAX_LEVEL = 1000
LOCAL_HERO_EXP_BASE = 100
LOCAL_HERO_EXP_GROWTH = 10
# 战斗给人物经验：基础 + 每个参考等级。
LOCAL_HERO_BATTLE_EXP_BASE = 200
LOCAL_HERO_BATTLE_EXP_PER_REF = 20


def hunter_exp_to_next(lv: int) -> int:
    return LOCAL_HERO_EXP_BASE + LOCAL_HERO_EXP_GROWTH * (max(1, int(lv)) - 1)


def hero_battle_exp(reference_lv: int) -> int:
    return LOCAL_HERO_BATTLE_EXP_BASE + LOCAL_HERO_BATTLE_EXP_PER_REF * max(0, int(reference_lv))


def _grant_hero_exp(connection, player_id: int, amount: int) -> int:
    """加人物经验并自动升级，返回新等级。"""
    if amount <= 0:
        return 0
    row = connection.execute(
        "SELECT lv, exp FROM players WHERE id=?", (player_id,)
    ).fetchone()
    if row is None:
        return 0
    lv = max(1, int(row["lv"] or 1))
    exp = int(row["exp"] or 0) + int(amount)
    while lv < LOCAL_HERO_MAX_LEVEL and exp >= hunter_exp_to_next(lv):
        exp -= hunter_exp_to_next(lv)
        lv += 1
    connection.execute("UPDATE players SET lv=?, exp=? WHERE id=?", (lv, exp, player_id))
    return lv
```

- [ ] **步骤 4：狩猎战斗发经验**

`_hunter_fight` 里 `pet_exp=_grant_pet_exp(...)` 之后加：

```python
        hero_ref = max((int(monster["lv"] or 1) for monster in monsters), default=1)
        hero_exp = hero_battle_exp(hero_ref)
        _grant_hero_exp(c, p["id"], hero_exp if is_win else hero_exp // 10)
```

- [ ] **步骤 5：运行确认通过**

运行：`pytest tests -q`
预期：全部 PASS。

- [ ] **步骤 6：Commit**

```bash
git add server/pet_hunter_server/app.py server/tests/test_app.py
git commit -m "feat(人物): 人物经验曲线与自动升级；狩猎胜利按怪物等级给人物经验"
```

---

### 任务 4：探险/擂台/副本也给人物经验

**文件：**
- 修改：`server/pet_hunter_server/app.py`
- 测试：`server/tests/test_app.py`

- [ ] **步骤 1：写失败测试**

```python
def test_explore_battle_grants_hero_exp(tmp_path: Path, monkeypatch):
    from pet_hunter_server import app as A

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "HeroEx")
    monkeypatch.setattr(A, "_explore_roll_event", lambda gid: 1)
    monkeypatch.setattr(A, "_record_is_win", lambda record: True)
    _envelope(client.post("/flash.do", data={"m": "show", "showId": "99", "uid": uid, "gid": 1}))
    _envelope(client.post("/flash.do", data={"m": "show", "showId": "103", "uid": uid}))
    _, profile = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "510", "uid": uid}
    ))
    assert (profile["lv"], profile["exp"]) != (1, 0)
```

- [ ] **步骤 2：运行确认失败**

运行：`pytest tests/test_app.py::test_explore_battle_grants_hero_exp -q`
预期：FAIL（exp 仍 0）。

- [ ] **步骤 3：探险战斗发经验**

`_explore_start` 战斗分支的 `_grant_pet_exp(...)` 之后加：

```python
        hero_exp = hero_battle_exp(reference_lv)
        _grant_hero_exp(c, p["id"], hero_exp if is_win else hero_exp // 10)
```

- [ ] **步骤 4：擂台/副本发经验**

`_arena_battle` 的 `_grant_pet_exp` 之后：

```python
        _grant_hero_exp(c, p["id"],
                        hero_battle_exp(max(LOCAL_ARENA_RIVAL_LEVEL, int(squad_lv))))
```

`_copy_battle` 的 `_grant_pet_exp` 之后：

```python
        _grant_hero_exp(c, player["id"],
                        hero_battle_exp(LOCAL_COPY_STAGE_LEVEL.get(hid, 1)))
```

- [ ] **步骤 5：运行确认通过**

运行：`pytest tests -q`
预期：全部 PASS。

- [ ] **步骤 6：Commit**

```bash
git add server/pet_hunter_server/app.py server/tests/test_app.py
git commit -m "feat(人物): 探险/擂台/副本战斗也给人物经验（失败十分之一）"
```

---

### 任务 5：属性口径统一（面板 = 战斗）

**文件：**
- 修改：`server/pet_hunter_server/app.py`
- 测试：`server/tests/test_app.py`

- [ ] **步骤 1：写失败测试**

```python
def test_hero_stats_grow_with_level_and_job_and_match_combat(tmp_path: Path):
    from pet_hunter_server import app as A

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "HeroStat")
    _, base = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "510", "uid": uid}
    ))
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET lv=50, job=10 WHERE uid=?", (uid,))
        connection.commit()
    _, grown = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "510", "uid": uid}
    ))
    for key in ("hp", "speed", "phy_att", "mag_att", "phy_def", "mag_def"):
        assert grown[key] > base[key], key

    with A._connect_database(database) as connection:
        row = connection.execute(
            "SELECT id,nick,lv,job,sex FROM players WHERE uid=?", (uid,)
        ).fetchone()
        worn = A._worn_equipment(connection, row["id"])
        combat = A._hunter_combat_stats(row, worn)
    assert combat == (grown["hp"], grown["phy_att"], grown["phy_def"])
```

- [ ] **步骤 2：运行确认失败**

运行：`pytest tests/test_app.py::test_hero_stats_grow_with_level_and_job_and_match_combat -q`
预期：FAIL（属性不随 lv/job 涨，或面板与战斗不一致）。

- [ ] **步骤 3：统一公式**

在 `ROLE_BASE_STATS` 后加：

```python
LOCAL_HERO_LEVEL_STAT_STEP = 0.006
LOCAL_HERO_JOB_STAT_STEP = 0.02


def _hero_stat_multiplier(lv: int, job: int) -> float:
    return (1 + LOCAL_HERO_LEVEL_STAT_STEP * (max(1, int(lv)) - 1)
            + LOCAL_HERO_JOB_STAT_STEP * (max(1, int(job)) - 1))


def _role_stats(worn: dict[int, sqlite3.Row], lv: int = 1, job: int = 1) -> dict[str, int]:
    """Base × (等级 + 称号) + 装备；面板与战斗共用这一份。"""
    mult = _hero_stat_multiplier(lv, job)
    totals = {key: round(value * mult) for key, value in ROLE_BASE_STATS.items()}
    for row in worn.values():
        for key in totals:
            totals[key] += row[key] or 0
    return totals
```

- [ ] **步骤 4：改所有调用点**

- `_player_payload`：`payload.update(_role_stats(worn, player["lv"], player["job"]))`。
- `_hunter_combat_stats`：
```python
    stats = _role_stats(worn, int(player_row["lv"] or 1),
                        int(player_row["job"] or 1) if "job" in player_row.keys() else 1)
    return stats["hp"], stats["phy_att"], stats["phy_def"]
```
- `_social_detail_response`（3/FriendInfo）：SELECT 加 `job`，player_fields 里 `"job":p["job"]`、`**_role_stats(worn, p["lv"], p["job"])`。
- 所有 `_hunter_combat_stats` 的 player 行 SELECT 补 `job`：狩猎 3061、`_fight_payload`、探险的 `p`、擂台/副本经 `_fight_payload`。

- [ ] **步骤 5：运行确认通过**

运行：`pytest tests -q`
预期：全部 PASS（注意既有战斗测试可能因属性略增而需要复核，但同级同称号时数值不变）。

- [ ] **步骤 6：Commit**

```bash
git add server/pet_hunter_server/app.py server/tests/test_app.py
git commit -m "feat(人物): 六维按等级/称号成长，面板与战斗统一走 _role_stats"
```

---

### 任务 6：人物面板显示装备技能

**文件：**
- 修改：`server/pet_hunter_server/app.py`
- 测试：`server/tests/test_app.py`

- [ ] **步骤 1：写失败测试**

```python
def test_player_payload_lists_worn_equipment_skills(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "HeroSkill")
    # 新角色的新手装默认在背包里（equipped=0），先穿上三件再看面板。
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE inventory SET equipped=1 WHERE player_id=1 AND team=3")
        connection.commit()
    _, profile = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "510", "uid": uid}
    ))
    ids = {entry["id"] for entry in profile["skills"]}
    assert 101 in ids and 5101 in ids, "烈焰之剑的 101:5101 要出现在人物技能里"
    assert all(isinstance(entry, dict) for entry in profile["skills"])
```

- [ ] **步骤 2：运行确认失败**

运行：`pytest tests/test_app.py::test_player_payload_lists_worn_equipment_skills -q`
预期：FAIL（`skills` 为空）。

- [ ] **步骤 3：实现汇总**

```python
def _equipment_skills(worn: dict[int, sqlite3.Row]) -> list[dict[str, int]]:
    """已穿装备自带的技能，按 id 去重排序；客户端 getSkill 读的是 .id。"""
    seen: set[int] = set()
    for row in worn.values():
        record = config_tables.equip_record(row["item_id"]) or {}
        for token in str(record.get("skills", "") or "").replace(",", ":").split(":"):
            token = token.strip()
            if token.isdigit():
                seen.add(int(token))
    return [{"id": skill_id} for skill_id in sorted(seen)]
```

`_player_payload` 里 `payload["skills"] = []` 改为 `_equipment_skills(worn)`。
`_social_detail_response` 的 `"skills":[]` 同样改为 `_equipment_skills(worn)`。

- [ ] **步骤 4：运行确认通过**

运行：`pytest tests -q`
预期：全部 PASS。

- [ ] **步骤 5：Commit**

```bash
git add server/pet_hunter_server/app.py server/tests/test_app.py
git commit -m "feat(人物): 面板汇总已穿装备的 skills（[{id}] 形状，客户端 getSkill 可读）"
```

---

### 任务 7：70/71/72 转职

**文件：**
- 修改：`server/pet_hunter_server/app.py`（`_job_list`/`_job_detail` 重写、新增 `_job_change`、路由 72）
- 测试：`server/tests/test_app.py`

- [ ] **步骤 1：写失败测试**

```python
def test_job_list_detail_and_change_follow_up_role(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "JobT")

    _, page = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "70", "uid": uid, "p": 1, "n": 9}
    ))
    rows = {row["job"]: row["state"] for row in page["list"]}
    assert rows[1] == 2 and rows[2] == 1 and rows[3] == 0

    _, detail = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "71", "uid": uid, "gid": 2}
    ))
    assert detail["need_lv"] == 400 and detail["diff_lv"] == 0
    assert set(detail["nextRole"]) >= {"now_hp", "next_hp", "now_speed", "next_speed"}
    assert detail["reward_goods"] == [{"id": 10016, "num": 1}]

    rejected = client.post(
        "/flash.do", data={"m": "show", "showId": "72", "uid": uid, "gid": 2}
    )
    assert rejected.get_data(as_text=True) == "-1:207"

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET lv=400 WHERE uid=?", (uid,))
        connection.commit()
    _, changed = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "72", "uid": uid, "gid": 2}
    ))
    assert changed["job"] == 2 and changed["lv"] == 400
    with sqlite3.connect(database) as connection:
        bag = connection.execute(
            "SELECT quantity FROM inventory WHERE player_id=1 AND item_id=10016"
        ).fetchone()
    assert bag is not None and bag[0] >= 1
```

再加一条 5 级转生掉级：

```python
def test_job_five_resets_level_to_one(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "Job5")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET lv=1000, job=4 WHERE uid=?", (uid,))
        connection.commit()
    _, changed = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "72", "uid": uid, "gid": 5}
    ))
    assert changed["job"] == 5 and changed["lv"] == 1
```

- [ ] **步骤 2：运行确认失败**

运行：`pytest tests/test_app.py -k "job_" -q`
预期：FAIL（70 只有 2 个 job、71 全是 0、72 未实现）。

- [ ] **步骤 3：实现 70/71/72**

```python
def _job_goods(raw: str) -> list[dict[str, int]]:
    goods: list[dict[str, int]] = []
    for part in str(raw or "").split(","):
        bits = part.split(":")
        if len(bits) >= 2 and bits[0].isdigit() and bits[1].isdigit() and int(bits[0]) > 0:
            goods.append({"id": int(bits[0]), "num": int(bits[1])})
    return goods


def _job_list(database_path: Path) -> Response:
    uid = _request_value("uid")
    try:
        page, size = int(_request_value("p", "1")), int(_request_value("n", "9"))
    except ValueError:
        return _pet_error(100)
    if page < 1 or not 1 <= size <= 9:
        return _pet_error(100)
    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id, job FROM players WHERE uid=?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
    current = int(player["job"] or 1)
    jobs = sorted(config_tables.up_role_table())
    entries = [
        {"job": job, "state": 2 if job <= current else (1 if job == current + 1 else 0)}
        for job in jobs
    ]
    start = (page - 1) * size
    return _protocol_response(70, {"list": entries[start:start + size]})


def _job_detail(database_path: Path) -> Response:
    try:
        job = int(_request_value("gid", ""))
    except ValueError:
        return _pet_error(100)
    table = config_tables.up_role_table()
    if job not in table:
        return _pet_error(400)
    uid = _request_value("uid")
    row = table[job]
    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id, lv, job FROM players WHERE uid=?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        worn = _worn_equipment(connection, player["id"])
    need = int(str(row.get("needLevel", "0")).strip() or 0)
    lower = int(str(row.get("lowerLevel", "0")).strip() or 0)
    now_stats = _role_stats(worn, int(player["lv"] or 1), int(player["job"] or 1))
    next_stats = _role_stats(worn, max(1, int(player["lv"] or 1) - lower), job)
    next_role: dict[str, int] = {}
    for key in ("hp", "speed", "phy_att", "mag_att", "phy_def", "mag_def"):
        next_role[f"now_{key}"] = now_stats[key]
        next_role[f"next_{key}"] = next_stats[key]
    return _protocol_response(71, {
        "job": job,
        "need_lv": need,
        "diff_lv": lower,
        "nextRole": next_role,
        "reward_goods": _job_goods(row.get("rewardGoods", "")),
    })


def _job_change(database_path: Path) -> Response:
    try:
        job = int(_request_value("gid", ""))
    except ValueError:
        return _pet_error(100)
    table = config_tables.up_role_table()
    if job not in table:
        return _pet_error(400)
    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id, lv, job FROM players WHERE uid=?", (_request_value("uid"),)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        current = int(player["job"] or 1)
        if job != current + 1:
            return _pet_error(100)
        need = int(str(table[job].get("needLevel", "0")).strip() or 0)
        if int(player["lv"] or 1) < need:
            return _pet_error(207)
        lower = int(str(table[job].get("lowerLevel", "0")).strip() or 0)
        new_lv = max(1, int(player["lv"] or 1) - lower)
        connection.execute(
            "UPDATE players SET job=?, lv=? WHERE id=?", (job, new_lv, player["id"])
        )
        goods = _job_goods(table[job].get("rewardGoods", ""))
        if goods:
            _grant_goods(connection, player["id"],
                         [(entry["id"], entry["num"]) for entry in goods])
    return _protocol_response(72, {"value": "ok", "job": job, "lv": new_lv})
```

> `next_role` 的键去重写法可简化成固定六项：hp/speed/phy_att/mag_att/phy_def/mag_def。

- [ ] **步骤 4：路由 72**

在 `/flash.do` 的路由里加：

```python
        if command == "show" and _request_value("showId") == "72":
            return _job_change(current_app.config["DATABASE"])
```

- [ ] **步骤 5：运行确认通过**

运行：`pytest tests -q`
预期：全部 PASS。

- [ ] **步骤 6：Commit**

```bash
git add server/pet_hunter_server/app.py server/tests/test_app.py
git commit -m "feat(人物): 70/71/72 接 upRole——称号列表/需求与降级/宝箱预览/手动转职（等级不够回 207）"
```

---

### 任务 8：维护脚本与文档

**文件：**
- 创建：`server/scripts/grant_hero_exp.py`
- 修改：`docs/handoff.md`、`docs/device-runbook.md`、`CHANGELOG.md`

- [ ] **步骤 1：脚本**

```python
"""Local maintenance: grant hunter exp or set level/job directly.

Usage:
    .venv/Scripts/python.exe scripts/grant_hero_exp.py --uid local-xxx --exp 5000
    .venv/Scripts/python.exe scripts/grant_hero_exp.py --uid local-xxx --lv 400 --job 2
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet_hunter_server.app import _connect_database, _grant_hero_exp  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uid", required=True)
    parser.add_argument("--exp", type=int, default=0)
    parser.add_argument("--lv", type=int, default=0)
    parser.add_argument("--job", type=int, default=0)
    parser.add_argument("--db", type=Path, default=Path("instance/game.sqlite3"))
    args = parser.parse_args()
    with _connect_database(args.db) as connection:
        row = connection.execute("SELECT id FROM players WHERE uid=?", (args.uid,)).fetchone()
        if row is None:
            print("no such uid")
            return 1
        if args.exp:
            print("lv ->", _grant_hero_exp(connection, row["id"], args.exp))
        if args.lv or args.job:
            sets, params = [], []
            if args.lv:
                sets.append("lv=?")
                params.append(args.lv)
            if args.job:
                sets.append("job=?")
                params.append(args.job)
            connection.execute(
                f"UPDATE players SET {', '.join(sets)} WHERE id=?",
                (*params, row["id"]),
            )
            print("updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **步骤 2：跑脚本验证**

```powershell
cd server
.\.venv\Scripts\python.exe scripts\grant_hero_exp.py --uid local-7b8aa3b620326df390f4e66d --exp 500
.\.venv\Scripts\python.exe scripts\grant_hero_exp.py --uid local-7b8aa3b620326df390f4e66d --lv 400 --job 2
```
预期：打印新等级/updated；510 能读到。

> 这是本地维护脚本，不要接进游戏命令；正式配置表/存档仍以服务器为准。

- [ ] **步骤 3：文档**

- `docs/handoff.md`：人物成长已完成项、70/71/72 语义、维护脚本用法。
- `docs/device-runbook.md`：真机检查点（人物面板等级/称号/六维/装备技能、转职页、经验上涨）。
- `CHANGELOG.md`：每个提交的 hash 与一句话。

- [ ] **步骤 4：Commit**

```bash
git add server/scripts/grant_hero_exp.py docs CHANGELOG.md
git commit -m "docs: 人物成长验证记录与本地跳级脚本"
```

---

## 验收清单

- [ ] `pytest tests -q` 全绿（新增测试 ≥ 8 条）。
- [ ] 真机：人物面板等级/称号/六维/装备技能真实显示；转职页 120 个称号、需求/降级/宝箱正确；等级不够点转职弹「转职需要的等级不够」。
- [ ] 人物经验来自狩猎/探险/擂台/副本，升级后 510 的 lv 增加、属性增加。
- [ ] 5 级转生后等级回到 1，宝箱进背包。
- [ ] 老存档（exp=0/job=1）行为不变。
