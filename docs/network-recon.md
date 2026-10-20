# Network Reconnaissance: Initial Findings

## Evidence source

String inspection of `APetHunter.swf` in the AIR 51 repack source and the SDK 23 diagnostic decode. These are static clues, not a complete protocol specification.

## Embedded endpoints and resources

- Default base URL: `http://123.196.114.169/`
- Server-list paths: `/data/android/server.xml` and `/serverTest.xml` (the SWF also contains `data/android/` as a relative prefix).
- Additional hard-coded HTTP hosts: `123.196.114.177`, `123.196.114.196`, and `123.196.114.185`.
- API path: `flash.do`.

The client displayed `Connection Timeout` while running on Android 16. That confirms the startup flow is blocked at a network step, but does not by itself prove whether every embedded host is offline or which one the current configuration selected.

The AIR SDK `swfdump -abc` disassembly identifies `cc.lv1.game::CommandManager.getCommandPost(int,Object)`. It creates `flash.net.URLVariables` and constructs a request path from `GameUtil.url + "flash.do?"`, then selects command names such as `login` and `autoLogin`. This confirms the dispatcher and request-building path; the complete variable serialization and response contract still need further inspection.

## Protocol clues

The SWF contains `HttpRequest`, `sendPost`, and `POST` strings. The command dispatcher contains `flash.do?` and action names including:

- `m=login`
- `m=autoLogin`
- `m=regc`
- `m=reg`
- `m=autoReg`
- `m=gcode`
- `m=im`
- `m=buldle` (spelling as embedded in the client)
- `m=show&showId=`

Related parameter names include `type=flash`, `uid`, `sn`, `sign`, `version`, `isTest`, and `uname`. Their exact encoding, ordering, signing rules, and whether values are mandatory are not yet established. A credential-like constant also appears in the SWF; its value is intentionally omitted from this report.

## What remains to establish

1. Decompile the ActionScript bytecode around server selection, request construction, signing, and response parsing.
2. Determine the selected server-list URL and exact first request from a controlled device trace or decompiled call path.
3. Record representative request and response bodies for startup, login/registration, character creation, and entering the home/map view.
4. Identify which gameplay actions are authoritative server operations and which can be supported by the bundled local data.
5. Specify a local URL redirect strategy. The client currently embeds remote IP addresses, so a loopback server alone will not receive traffic without changing the client routing or adding a device-side mapping layer.

Do not implement guessed responses as if they were verified. Start with a captured/decompiled vertical slice and persist any local user state in a local database only after the state model is understood.
