# 道具场景过滤 + 养成流程 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 背包按场景只显示可用的道具；训练中的宠物退出出战槽、从所有选宠/战斗入口消失；训练收益两列分别记账。

**架构：** 客户端 22 号请求补一个 `target`（0=人物/家园，宠物 index=宠物），服务端在分页前按 `use_type` 过滤；训练状态统一用 `train_end <= strftime('%s','now')` 判断，服务端各宠物查询加同一个 SQL 片段；训练开始/结算改成 `train_gain`/`train_gain2` 两列。

**技术栈：** Python 3.11 + Flask + SQLite（`server/pet_hunter_server/app.py`），pytest，FFDec + AIR SDK（客户端重打包）。

**规格：** `docs/superpowers/specs/2026-10-24-bag-context-and-character-growth-design.md` 第三、4.1 节。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `server/pet_hunter_server/app.py` | 22 号过滤、宠物可用性 SQL、训练开始/结算 |
| `server/tests/test_app.py` | 新增 5 组测试 |
| `client/air51-repack/rebuild-client-patches.py` | BagListUI 的 `target` 补丁 |
| `docs/device-runbook.md` / `docs/handoff.md` / `CHANGELOG.md` | 验证记录与交接 |

---

### 任务 1：宠物可用性（训练中不可选/不可战）

**文件：**
- 修改：`server/pet_hunter_server/app.py`（常量区 + 约 10 处宠物查询）
- 测试：`server/tests/test_app.py`

- [ ] **步骤 1：新增 SQL 片段常量**

在 `LOCAL_DEFAULT_PET_CAPACITY` 附近加入：

```python
# 训练中的宠物不参与选宠/出战。用 SQLite 自己的 epoch 比较，避免给十几条
# 宠物查询都加一个 time.time() 绑定参数。
PET_READY_SQL = "COALESCE(train_end, 0) <= CAST(strftime('%s','now') AS INTEGER)"
```

- [ ] **步骤 2：写失败测试**

在 `test_app.py` 末尾追加：

```python
def test_training_pet_is_hidden_from_pickers_and_battles(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "TrainEx")
    with sqlite3.connect(database) as connection:
        pet_index = connection.execute(
            "SELECT id FROM pets WHERE player_id=1 ORDER BY id LIMIT 1"
        ).fetchone()[0]
        connection.execute(
            "UPDATE pets SET train_state=1, train_end=9999999999 WHERE id=?", (pet_index,)
        )
        connection.commit()

    _, picker = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "505", "uid": uid, "p": 1, "n": 9}
    ))
    assert all(row["index"] != pet_index for row in picker["list"])

    _, fight_picker = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "42", "uid": uid, "p": 1, "n": 9}
    ))
    assert all(row["index"] != pet_index for row in fight_picker["list"])

    rejected = client.post(
        "/flash.do", data={"m": "show", "showId": "44", "uid": uid, "index": pet_index}
    )
    assert rejected.get_data(as_text=True).startswith("-1:")

    _envelope(client.post("/flash.do", data={"m": "show", "showId": "99", "uid": uid, "gid": 1}))
    _, battle = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "103", "uid": uid}
    ))
    used = {row.get("index") for row in battle["battle_result"]["att_list"] if row.get("index")}
    assert pet_index not in used
```

- [ ] **步骤 3：运行确认失败**

运行：`cd server; .\.venv\Scripts\python.exe -m pytest tests/test_app.py::test_training_pet_is_hidden_from_pickers_and_battles -q`
预期：FAIL（505/42 里仍有该宠，44 成功）。

- [ ] **步骤 4：给查询加过滤**

用 `PET_READY_SQL` 修改下列位置（都是 `AND ...` 形式追加）：

1. `_hunter_fight` 的宠物查询：
```python
rows=c.execute(f"SELECT id AS 'index',pet_id AS id,icon,name,lv,pro_hp,pro_speed,pro_phy_att,pro_mag_att,pro_phy_def,pro_mag_def FROM pets WHERE player_id=? AND battle_state=0 AND is_locked=0 AND {PET_READY_SQL} ORDER BY id LIMIT 2",(p["id"],)).fetchall()
```
2. `_explore_start` 的 `squad_lv`、`pet_rows`、`explore_rows`、第二次 `squad_lv`（4 处）：
```python
f"... WHERE player_id=? AND battle_state=0 AND is_locked=0 AND {PET_READY_SQL} ..."
```
3. `_choose_pet_list`（42）：
```python
f"""SELECT id AS "index", pet_id AS id, icon, name, lv FROM pets
    WHERE player_id=? AND is_locked=0 AND {PET_READY_SQL} ORDER BY id LIMIT ? OFFSET ?"""
```
4. `_fight_payload` 的 `rows`（6/24/74 共用）加 `AND {PET_READY_SQL}`。
5. `_arena_battle` 的 `squad_lv`、`arena_pets`、第二次 `squad_lv`（3 处）加 `AND {PET_READY_SQL}`。
6. `_copy_battle` 的 `copy_pets` 加 `AND {PET_READY_SQL}`。
7. `_training_list`（505）：
```python
f"SELECT id AS 'index',pet_id AS id,icon,name,lv FROM pets WHERE player_id=? AND battle_state=0 AND {PET_READY_SQL} ORDER BY id"
```
8. `_hunter_task`（5）的出战宠物查询加 `AND {PET_READY_SQL}`：
```python
f" WHERE player_id=? AND squad_slot>0 AND is_locked=0 AND {PET_READY_SQL}"
```
9. `_choose_battle_pet`（44）在 `row is None` 之后加：
```python
        if int(row["train_end"] or 0) > int(time.time()):
            return _pet_error(100)
```
10. `_arena_fighter`（506）的宠物查询加 `AND {PET_READY_SQL}`。

> 说明：`pets` 表没有别名，片段可直接拼；若以后加别名，把 `train_end` 改成 `别名.train_end`。

- [ ] **步骤 5：运行测试确认通过**

运行：`cd server; .\.venv\Scripts\python.exe -m pytest tests -q`
预期：全部 PASS。

- [ ] **步骤 6：Commit**

```bash
git add server/pet_hunter_server/app.py server/tests/test_app.py
git commit -m "fix(养成): 训练中的宠物退出选宠/出战——505/42/44/103/6/24/74/506 统一按 train_end 过滤"
```

---

### 任务 2：训练开始自动下场 + 两列收益

**文件：**
- 修改：`server/pet_hunter_server/app.py`（`_initialize_database` 的 pets ALTER、`_training_overview`、`_training_action`）
- 测试：`server/tests/test_app.py`

- [ ] **步骤 1：写失败测试**

```python
def test_training_starts_benches_the_pet_and_books_both_columns(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "TrainCol")
    with sqlite3.connect(database) as connection:
        pet_index = connection.execute(
            "SELECT id FROM pets WHERE player_id=1 ORDER BY id LIMIT 1"
        ).fetchone()[0]
        connection.execute(
            "UPDATE pets SET squad_slot=1, pro_hp=995, pro_speed=998 WHERE id=?",
            (pet_index,),
        )
        connection.commit()

    _, started = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "10", "uid": uid,
                           "index": pet_index, "ttype": 1}
    ))
    assert started["pet"]["id"] > 0
    with sqlite3.connect(database) as connection:
        squad_slot, gain1, gain2 = connection.execute(
            "SELECT squad_slot, train_gain, train_gain2 FROM pets WHERE id=?",
            (pet_index,),
        ).fetchone()
    assert squad_slot == 0, "starting training must bench the pet"
    assert (gain1, gain2) == (5, 2), "995 只能加 5，998 只能加 2"

    # 结束训练后两列各按自己的额度结算。
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE pets SET train_end=1 WHERE id=?", (pet_index,))
        connection.commit()
    client.post("/flash.do", data={"m": "show", "showId": "504", "uid": uid})
    with sqlite3.connect(database) as connection:
        pro_hp, pro_speed = connection.execute(
            "SELECT pro_hp, pro_speed FROM pets WHERE id=?", (pet_index,)
        ).fetchone()
    assert (pro_hp, pro_speed) == (1000, 1000)
```

- [ ] **步骤 2：运行确认失败**

运行：`pytest tests/test_app.py::test_training_starts_benches_the_pet_and_books_both_columns -q`
预期：FAIL（`train_gain2` 列不存在 / squad_slot 仍 1）。

- [ ] **步骤 3：加列与迁移**

在 pets 的 `ALTER TABLE` 列表（`train_gain` 之后）加：

```python
            ("train_gain2", "ALTER TABLE pets ADD COLUMN train_gain2 INTEGER NOT NULL DEFAULT 0"),
```

- [ ] **步骤 4：结算两列**

`_training_overview` 的 `finished` 查询加 `train_gain2`，结算改为：

```python
        for pet in finished:
            columns = LOCAL_TRAIN_GAIN.get(int(pet["train_type"] or 0), ())
            gains = (int(pet["train_gain"] or 0), int(pet["train_gain2"] or 0))
            for column, gain in zip(columns, gains):
                current = int(pet[column] or 0)
                step = min(gain, max(0, LOCAL_PRO_CAP - current))
                if step:
                    c.execute(f"UPDATE pets SET {column} = ? WHERE id = ?",
                              (current + step, pet["id"]))
            c.execute(
                "UPDATE pets SET train_state=0, train_type=0, train_end=0,"
                " train_gain=0, train_gain2=0 WHERE id=?", (pet["id"],)
            )
```

- [ ] **步骤 5：开始训练时记账并下场**

`_training_action` 中把 `applied` 的计算与 UPDATE 改为：

```python
        per_run = _train_gain(row["lv"] or 1) * (3 if ttype == 3 else 1)
        columns = LOCAL_TRAIN_GAIN[ttype]
        gains: list[int] = []
        for column in columns:
            current = int(row[column] or 0)
            gains.append(min(per_run, max(0, LOCAL_PRO_CAP - current)))
        if not any(gains):
            return _pet_error(100)
        c.execute(
            "UPDATE pets SET train_state=?, train_type=?, train_end=?,"
            " train_gain=?, train_gain2=?, squad_slot=0 WHERE id=?",
            (ttype, ttype, now + LOCAL_TRAIN_SECONDS,
             gains[0], gains[1] if len(gains) > 1 else 0, idx),
        )
```

并把响应里的 `applied` 构造改成：

```python
    applied = dict(zip(columns, gains))
    if reward_exp:
        ...
    adds = {f"add_{column.split('_', 1)[1]}_tp": value for column, value in applied.items()}
```

> `columns/gains` 在 `with` 块内定义，响应在块外使用；如报作用域问题，把它们在 `with` 前初始化为 `columns=(); gains=[]`。

- [ ] **步骤 6：运行测试确认通过**

运行：`pytest tests -q`
预期：全部 PASS。

- [ ] **步骤 7：Commit**

```bash
git add server/pet_hunter_server/app.py server/tests/test_app.py
git commit -m "fix(养成): 开始训练自动下场；两列强化收益分别记账，避免接近上限时第二列超发"
```

---

### 任务 3：22 号按场景过滤道具

**文件：**
- 修改：`server/pet_hunter_server/app.py`（`_player_inventory`）
- 测试：`server/tests/test_app.py`

- [ ] **步骤 1：写失败测试**

```python
def test_bag_filters_items_by_scene_target(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "BagCtx")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO inventory (player_id,item_id,team,quantity,icon,item_type,use_type)"
            " VALUES (1,10001,1,1,10001,0,1),"   # 人物用
            " (1,10030,1,1,10030,0,0),"          # 通用/特殊
            " (1,10011,1,1,10011,0,2)"           # 宠物用
        )
        connection.commit()

    def ids(target=None):
        data = {"m": "show", "showId": "22", "uid": uid, "ttype": 1, "p": 1, "n": 9}
        if target is not None:
            data["target"] = target
        _, payload = _envelope(client.post("/flash.do", data=data))
        return {row["id"] for row in payload["goods_list"]}, payload["bag_size"]

    hero, hero_size = ids(0)
    assert hero == {10001, 10030}
    assert hero_size == 3, "bag_size 仍是该 tab 的总行数"

    pet, _ = ids(1)
    assert pet == {10011}

    legacy, _ = ids(None)
    assert legacy == {10001, 10030, 10011}, "旧客户端不带 target 时保持全量"
```

- [ ] **步骤 2：运行确认失败**

运行：`pytest tests/test_app.py::test_bag_filters_items_by_scene_target -q`
预期：FAIL（三个请求都返回全量）。

- [ ] **步骤 3：实现过滤**

`_player_inventory` 解析参数处加：

```python
    try:
        target_raw = _request_value("target", "").strip()
        target = int(target_raw) if target_raw else -1
    except ValueError:
        target = -1
```

把 `else` 分支（team 1/2）的查询改成：

```python
        else:
            where = "player_id=? AND team=?"
            params: list[int] = [player["id"], item_type]
            if item_type == 1 and target >= 0:
                wanted = (0, 1) if target == 0 else (2,)
                placeholders = ",".join("?" for _ in wanted)
                where += f" AND use_type IN ({placeholders})"
                params.extend(wanted)
            rows = connection.execute(
                f"""SELECT id AS "index", item_id AS id, team, quantity AS num, icon,
                           item_type AS type, use_type, level
                    FROM inventory WHERE {where}
                    ORDER BY id LIMIT ? OFFSET ?""",
                (*params, page_size, (page - 1) * page_size),
            ).fetchall()
            count = connection.execute(
                "SELECT COUNT(*) FROM inventory WHERE player_id = ? AND team = ?",
                (player["id"], item_type),
            ).fetchone()[0]
```

> `bag_size` 用未过滤的总数；`goods_list` 用过滤后的分页。

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests -q`
预期：全部 PASS。

- [ ] **步骤 5：Commit**

```bash
git add server/pet_hunter_server/app.py server/tests/test_app.py
git commit -m "feat(背包): 22 号按 target 过滤——人物只回 useType 0/1，宠物只回 2；旧客户端不带 target 保持全量"
```

---

### 任务 4：客户端 BagListUI 补丁 + 重打包

**文件：**
- 修改：`client/air51-repack/rebuild-client-patches.py`
- 产物：`build/input-localwifi/APetHunter.swf`、`build/out/PetHunterG-LocalWiFi.apk`

- [ ] **步骤 1：先验证 BagListUI 能否被 FFDec 重编译**

```powershell
$out="$env:TEMP\bagtest"; Remove-Item -Recurse -Force $out -ErrorAction SilentlyContinue
& 'D:\Configure\jdk17\bin\java.exe' -jar 'D:\Tool\FFDec-26.4.0\ffdec.jar' -export script $out 'F:\git\PetHunterG\client\air51-repack\build\input-remote\APetHunter.swf'
# 只导入 BagListUI 一个文件
$only="$env:TEMP\bagonly\scripts\cc\lv1\game\ui"; New-Item -ItemType Directory -Force $only | Out-Null
Copy-Item "$out\scripts\cc\lv1\game\ui\BagListUI.as" $only
& 'D:\Configure\jdk17\bin\java.exe' -jar 'D:\Tool\FFDec-26.4.0\ffdec.jar' -importScript 'F:\git\PetHunterG\client\air51-repack\build\input-remote\APetHunter.swf' "$env:TEMP\bagonly\out.swf" "$env:TEMP\bagonly"
```
- 成功：`out.swf` 存在 → 继续。
- 失败（`findproperty` 等）：**停止本任务**，改用“客户端本地过滤”退路并回来找用户确认。

- [ ] **步骤 2：给重建脚本加补丁**

在 `rebuild-client-patches.py` 里加：

```python
    # 7) BagListUI: 22 号把场景 target 带给服务端
    p = ui / "BagListUI.as"
    src = p.read_text(encoding="utf-8")
    old = ('CommandManager.send(CommandManager.BAG_INFO_KEY,{\n'
           '            "ttype":data.ttype,\n'
           '            "p":_page,\n'
           '            "n":_item_num\n'
           '         });')
    new = ('CommandManager.send(CommandManager.BAG_INFO_KEY,{\n'
           '            "ttype":data.ttype,\n'
           '            "p":_page,\n'
           '            "n":_item_num,\n'
           '            "target":data.target == null ? 0 : data.target\n'
           '         });')
    if old not in src:
        raise SystemExit("bag target anchor missing")
    src = src.replace(old, new)
    p.write_text(src, encoding="utf-8")
```

并把导入循环改成：

```python
    for name in ("ExploreMapListUI", "HireShopUI", "HireMountsUI",
                 "HireShopInfoUI", "BagListUI"):
```

- [ ] **步骤 3：重建 SWF 并检查补丁**

```powershell
cd F:\git\PetHunterG\client\air51-repack
..\..\server\.venv\Scripts\python.exe rebuild-client-patches.py
# 导出确认
$out="$env:TEMP\localwifi-as3"; Remove-Item -Recurse -Force $out -ErrorAction SilentlyContinue
& 'D:\Configure\jdk17\bin\java.exe' -jar 'D:\Tool\FFDec-26.4.0\ffdec.jar' -export script $out build\input-explore\APetHunter.swf
Select-String -Path "$out\scripts\cc\lv1\game\ui\BagListUI.as" -Pattern '"target"' 
```
预期：能看到 `"target":data.target == null ? 0 : data.target`。

- [ ] **步骤 4：做 localwifi 输入并改 URL**

```powershell
cd F:\git\PetHunterG\client\air51-repack
Remove-Item -Recurse -Force build\input-localwifi -ErrorAction SilentlyContinue
Copy-Item -Recurse build\input-explore build\input-localwifi
Get-ChildItem build\input-localwifi -Filter "step-*.swf" | Remove-Item -Force
Get-ChildItem build\input-localwifi -Filter "APetHunter-*.swf" | Remove-Item -Force
..\..\server\.venv\Scripts\python.exe patch_swf_url.py build\input-localwifi\APetHunter.swf build\input-localwifi\APetHunter.swf --replace "http://43.173.99.241:8080=http://127.0.0.1:8080" --replace-all
```

- [ ] **步骤 5：打包并验证**

```powershell
$sign = Get-Content build\localwifi-signing.txt
$pw = (($sign | Where-Object { $_ -like 'pass=*' }) -replace '^pass=','')
$env:JAVA_HOME='D:\Configure\jdk17'; $env:PATH="$env:JAVA_HOME\bin;$env:PATH"
& 'D:\Tool\AIRSDKs\AIRSDK_51.4.1\bin\adt.bat' -package -target apk -arch armv7 -storetype pkcs12 -keystore build\localwifi.p12 -storepass $pw build\out\PetHunterG-LocalWiFi.apk build\PetHunter-localwifi.xml -platformsdk 'D:\Tool\AndroidSdk' -C build\input-localwifi .
$bt='D:\Tool\AndroidSdk\build-tools\36.0.0'
& "$bt\aapt.exe" dump badging build\out\PetHunterG-LocalWiFi.apk | Select-Object -First 1
```
预期：`package: name='air.com.lv1.hunter.localwifi' ... versionName='2.7.3'`。

- [ ] **步骤 6：覆盖安装（保留登录）**

```powershell
& F:/SoftWare/adb/adb.exe -s 10.89.127.80:5555 install -r build\out\PetHunterG-LocalWiFi.apk
```
安装器弹窗点“安装/更新”，完成后点“打开”；确认前台包名。

- [ ] **步骤 7：Commit 脚本**

```bash
git add client/air51-repack/rebuild-client-patches.py
git commit -m "feat(客户端): BagListUI 22 号请求带 target，供服务端按人物/宠物场景过滤道具"
```

---

### 任务 5：文档与真机验证

- [ ] 更新 `docs/device-runbook.md`：新 APK 哈希、安装/更新方式、人物/宠物背包过滤的界面与请求证据。
- [ ] 更新 `docs/handoff.md`：阶段 1 已完成项、客户端补丁位置。
- [ ] 更新 `CHANGELOG.md`。
- [ ] 真机验证：
  - 人物→使用道具：只出现人物/通用道具，宠物道具不显示；
  - 宠物→使用道具：只出现宠物道具；
  - 训练一只宠物后返回选宠页：它不在列表里；狩猎/探险选宠也看不到它；
  - 训练倒计时结束再打开养成页：属性增加，宠物回到可用状态。
- [ ] Commit：

```bash
git add docs CHANGELOG.md
git commit -m "docs: 阶段1（道具场景过滤 + 训练流程）验证记录"
```
