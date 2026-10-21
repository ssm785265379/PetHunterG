# Flask LAN Prototype

This LAN-only prototype supports local account registration/login, one account-bound character, initial profile loading, and an empty initial task list. Other gameplay commands remain unimplemented and return HTTP 501.

## Requirements

- Python 3.11 or newer
- USB debugging enabled and the phone connected with ADB

## Install

From PowerShell:

```powershell
cd F:\git\PetHunterG\server
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run over USB

The client uses `127.0.0.1:8080`; ADB reverse forwarding maps the phone's loopback port to this computer. This avoids embedding a changing Wi-Fi address in the APK.

```powershell
.\.venv\Scripts\python.exe -m pet_hunter_server --host 127.0.0.1 --port 8080
F:\SoftWare\adb\adb.exe reverse tcp:8080 tcp:8080
F:\SoftWare\adb\adb.exe reverse --list
```

The server binds only to loopback. Re-run `adb reverse tcp:8080 tcp:8080` after reconnecting the USB device or restarting ADB; the mapping may not persist. Debug mode and request access lines are disabled; request logs contain the command and field names, not parameter values.

On the phone, `http://127.0.0.1:8080/health` should return:

```json
{"mode":"lan-prototype","status":"ok"}
```

If it does not connect, verify `adb devices -l`, `adb reverse --list`, and that the local health endpoint responds on the computer. No Wi-Fi address or inbound firewall rule is needed for this USB path.

## Current routes

- `GET /health`: connectivity check.
- `GET /data/android/<locale>/server.xml`, `/data/android/server.xml`, `/server.xml`, `/serverTest.xml`: serve the configured XML fixture verbatim; if the requested fixture is absent, return HTTP 503 `server_list_not_configured`.
- `POST /flash.do` supports the observed account/character path: `regc` registers an account, `login` authenticates it, `reg` creates and binds a character, and `autoLogin` restores that character. `autoReg` remains available for the legacy quick-create path. `showId=510` returns the character profile and `showId=511` returns an empty initial task list.
- `showId=22` returns the character's persisted inventory for the requested `ttype` tab; `showId=11`/`showId=12` return the pet list and pet detail from a per-character `pets` table.
- `showId=39` returns equipment detail (`index`, `ttype=3`) from a persisted `inventory` row: `money,index,id,icon,level,star,pro,hp,phy_att,mag_att,phy_def,mag_def,speed`. The client looks up `pic[id].name`, instantiates `p<icon>` with no try/catch, and hides the sell button when `money > 0`. Selling (68/69) is not implemented, so a positive local `money` deliberately hides that button.
- Pet mutations: `showId=18` renames (`index`, `pName`), `showId=55` toggles lock (`index`), `showId=15` releases (`index`), `showId=14` evolves (`index`), and `showId=40` expands capacity. Failures return HTTP 200 with the client's own `-1:<error.txt key>` code (204, 504, 505, 506, 514, 517, 524, plus 100/103 for malformed or unknown players) so the game shows its bundled message instead of a network error.
- Account passwords are stored as salted scrypt hashes in `server/instance/game.sqlite3`; request logs contain field names only. Unimplemented commands still return HTTP 501 rather than a guessed success.

### Pet defaults and maintenance

Each newly created character receives a local starter pack: 火龙 (config id/iconId `1001`, three stars) and 小火猴 (`2019`, five stars). Both icons (`p1001`, `p2019`) exist in the bundled pet SWFs, so the client renders them without `#1065`; the five-star pet also makes the client's lock-confirmation branch (requires `star >= 5`) reachable. Pet capacity is 30 slots, cap 90, +9 per expansion. All of these are explicit **local defaults**, not recovered original-server rules.

Local evolution chains (config ids): `1001 → 1002 → 1003` and `2019 → 2020 → 2021`, with local `need_lv` values 5 and 10 and zero currency/goods cost. The client only displays these; the original table is not recoverable. Locked pets cannot be evolved or released; pets with a non-zero `battle_state` cannot be released.

Saves created before a starter pet existed can be backfilled idempotently. A character is skipped once any non-starter pet exists, so an evolved roster is never re-seeded:

```powershell
.\.venv\Scripts\python.exe scripts\grant_starter_pets.py
```

`free_goods_*` reward payloads for release are intentionally omitted; the client goes straight back to the list, which re-requests `showId=11`.

### Equipment defaults and maintenance

Each character also receives one local starter equipment, 烈焰之剑 (`equip.txt` id/iconId `20001`, team 3, slot type 1, one star, `phy_att`/`mag_att` 20, everything else 0). The `p20001` class exists in the bundled `skin.swf` and `pic.txt[20001]` supplies the name, so the client renders it without `#1065`. This is an explicit **local default**, not a recovered original-server rule. The `inventory` table now persists icon, item subtype, `use_type`, enhancement level, star, quality and the six combat stats.

Bag-list rows need `icon` as the full class name (`p20001`), because `BagListUI` passes it to `IconItem`, which resolves it verbatim; detail 39 instead needs the numeric icon id and prefixes `p` itself. Equipment rows also return `type: 0` so the client's `onMouseUpItem` switch falls through to its `default` branch and sends `EQUIP_INFO` (39) instead of mistaking the equipment slot type for a pet-item action (cases 1/2/9/24/25/27).

Saves created before the starter equipment existed can be backfilled idempotently:

```powershell
.\.venv\Scripts\python.exe scripts\grant_starter_equipment.py
```

`server/fixtures/data/android/server.xml` currently contains a **synthetic diagnostic node**, not an authentic server list. Its `id`, `name`, `icon`, `n`, and `url` fields follow the SWF's XML access pattern; it points to `http://127.0.0.1:8080/`, forwarded over the connected USB debugging session. `icon=clip_back_login` is a temporary known-loaded `MovieClip`; `n=0` separately selects the bundled `clip_server_0` status symbol. Do not treat this fixture as recovered production data.

## Client connection status

The checked-in source SWF remains unchanged. The local side-by-side AIR 51 test APK is built from a copy with the default and three fallback hosts redirected to `http://127.0.0.1:8080/`. Use the `localusb` package for USB reverse forwarding; rebuild only if the port changes, not when Wi-Fi IPs change.

The OPPO phone reached this service and requested `GET /data/android/zh-CN/server.xml`; the locale route serves the synthetic node above. Account-backed registration/login, character creation, home profile (`showId=2`), inventory list (`showId=22`), the pet list/detail (`showId=11`/`12`), the pet write commands (`14`/`15`/`18`/`40`/`55`), and equipment detail (`showId=39`) have all been exercised against the live database. The pet list rendered `Lv5 阿火` and the detail screen rendered 名称/星级/等级/属性/进化 plus the renamed and evolved state without a crash. The equipment tab rendered `Lv1 烈焰之剑` and its detail rendered 星级/生命 0/物攻 20/魔攻 20/物防 0/魔防 0/速度 0 with no `#1065`. The write commands' in-game button/confirm taps were not automated because the confirm controls are image assets. Remaining gameplay branches (shop, tasks, hunting, exploration, social) are still unimplemented.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

The suite currently covers the account/character path, profile, inventory, equipment detail (39), and the full pet read/write surface (11/12/14/15/18/40/55), including cross-player isolation and locked/battle-state guards: 43 tests pass.
