# Device Test Runbook

## Device and connection

- Phone: OPPO PHB110, Android 16, supports `arm64-v8a` and `armeabi-v7a`.
- Use `F:\SoftWare\adb\adb.exe` and the already-running `F:\SoftWare\adb\scrcpy.exe` for device work.
- The `localusb` diagnostic client uses `http://127.0.0.1:8080/`. Start Flask on the PC loopback interface, then run `F:\SoftWare\adb\adb.exe reverse tcp:8080 tcp:8080` after USB/ADB reconnects. Verify with `adb reverse --list`.
- Do not rely on the PC Wi-Fi address; it changes in the office network. The ADB reverse mapping was verified and the phone's server-list request reached Flask as source `127.0.0.1` with HTTP 200.

## APK installation

1. Preserve existing packages. Install diagnostics under a new package identity unless intentionally replacing one.
2. Starting `adb install` opens the Android installer. Wait for the confirmation dialog and tap **安装**; do not assume the command alone completed installation.
3. Wait for **安装完成**, then tap **打开** (the button may be labeled **进入** on some installer versions). Verify the app package is in the foreground.
4. Android 16 may show a separate system warning that the app is 32-bit. This is not the install confirmation. Acknowledge **确定** to continue testing. Do not change system security settings to hide it. An ARM64 build is the candidate way to avoid this warning; it has not yet been built/verified.

## Game flow

1. On startup, select the visible `LAN Local Test` server row.
2. The next screen offers **快速游戏** and **账号登陆**. For account-backed testing, tap **账号登陆**.
3. On the login form, enter username and password, then tap **登陆**. If creating the account first, tap **注册** to open the three-field form.
4. Registration fields are username, password, and confirm password. The confirmation must exactly match the password. Submit only after all three fields are visibly populated and the two password fields show the same number of masked characters.
5. The game uses a native soft keyboard that changes the visible layout. Re-observe the screen after each field entry; do not reuse touch coordinates from a screenshot taken with the keyboard hidden. Avoid Tab/Back key shortcuts while entering values because they can change focus or trigger the game's exit prompt.
6. Server request logs intentionally include only command names and field names, never credential values.

## Current checkpoint

- Installed side-by-side package: `air.com.lv1.hunter.iconless.localusb`; earlier `air.com.lv1.hunter.iconless.ipfix` remains installed. Neither was uninstalled.
- The `localusb` package uses the dynamic-IP-independent loopback URL in all four server URL constants. The SWF source in `src/` remains untouched.
- Later device evidence supersedes the earlier incomplete registration attempt: the saved session restored through **快速游戏**, reached the main map, and issued successful `autoLogin`, `showId=510`, and `showId=511` requests. Credentials are intentionally omitted here.
- Tapping 家园 previously produced `showId=2` HTTP 501 and returned to login. The server now implements that response and has regression coverage, but the patched flow has not yet been rechecked on screen.
- Current Flask process is listening on `127.0.0.1:8080`; `/health` is healthy and the test suite last passed 23 tests. Current ADB state is `24086b59 unauthorized`, so reauthorize USB debugging on the phone before continuing screen checks, then reapply `adb reverse tcp:8080 tcp:8080`.
- USB debugging was reauthorized at 13:01 local device time; device `24086b59` is online and reverse `tcp:8080` is active. 快速游戏 restored the session and the main map was visible. Tapping 家园 now renders the saved level-1 profile and local baseline profession/guild/rank values; correlated `showId=2` returned HTTP 200 (205 bytes).
- The 道具入口 correlated with `showId=22`, HTTP 200 (52 bytes), and a visible empty grid with `0/100`. Capacity 100 is the documented local default, not a recovered original-server value. Only this category has been conclusively correlated so far; other categories remain to verify.
- The 32-bit compatibility warning was acknowledged once after install. Whether it appears on every install or only first launch is not yet established.
- Pet module check (2026-10-21 14:33 device time, device `24086b59`, package `air.com.lv1.hunter.iconless.localusb`, server `127.0.0.1:8080`, reverse `tcp:8080` active): 快速游戏 restored the session (autoLogin → 510 → 511), then 主地图「牧场」→ 宠物 opened the pet list. Correlated `showId=11` (HTTP 200, 138 bytes) and the grid rendered `Lv1 火龙`; tapping the cell correlated `showId=12` (HTTP 200, 97 bytes) and the detail screen showed 名称 火龙 / 星级 ★★★ / 等级 1 / 属性 火 / 不能再进化. No #1065 or crash was observed. The starter pet and capacity 30 are local defaults, not recovered original-server values.
- Equipment detail check (2026-10-21 15:10-15:11): after a server restart onto the 43-test code and a database backfill of the starter equipment, 快速游戏 restored the session, 家园 opened HomeUI, the 装备 button opened the bag's equipment tab, and the grid rendered `Lv1 烈焰之剑` (icon `p20001`, name from `pic[20001]`). Tapping the cell emitted `showId=39` (HTTP 200, 142 bytes) and the detail screen rendered 装备信息【Lv1 烈焰之剑】/ 星级 ★ / 生命 0 / 物攻 20 / 魔攻 20 / 物防 0 / 魔防 0 / 速度 0, with no `#1065` and no crash. First attempt failed: equipment rows carried `type=1`, which `BagListUI.onMouseUpItem` treats as a pet-item action and answered with 501; returning `type=0` routes to the 39 branch.
- Pet write commands (2026-10-21 14:49-14:51): server restarted onto the 39-test code. Writes were exercised against the live SQLite database over HTTP: rename 18 persisted (`name=阿火`), lock 55 returned `{"value":"true"}` then `{"value":"false"}`, evolve 14 returned the new detail (1001→1002, `next_pet`→1003), expand 40 changed `max_pet_num` 30→39, release 15 refused a locked pet with `-1:524` and succeeded after unlock. The on-device client then re-fetched and rendered the results: list showed `Lv5 阿火`, detail showed 名称 阿火 / 星级 ★★★ / 等级 5 / 属性 火 / 进化 烈焰龙 需要 Lv10, with the `p1002` icon resolving and no crash. The write commands' in-game button/confirm taps were **not** automated (confirm buttons are image assets and this session cannot read the screen), so UI-initiated write flow remains for a manual pass.
