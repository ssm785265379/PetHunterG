# Pet Hunter G Offline Project: Progress v1

**Date:** 2026-10-20  
**Goal:** Run the original client on Android 16, then investigate a private offline service simulator with local saves.

## Result

The original AIR 3.4 package failed on Android 16 because its native `libCore.so` depends on the unavailable/private `libstagefright.so` library. An SDK 28 compatibility APK did not solve that linker failure.

The client resources were repackaged with HARMAN AIR SDK 51.4.1. The resulting ARMv7 test package installs on the OPPO PHB110 (Android 16 / API 36), starts without the prior `libCore.so` failure, and remains in the foreground. It reaches the game's own `连接超时` screen. This verifies startup/runtime compatibility, not playable offline gameplay.

## Build and device facts

- Source APK: `C:\Users\ssm\Desktop\552114.apk` (kept unchanged).
- Installed package identity for the original-name build: `air.com.lv1.hunter`.
- Side-by-side test identity: `air.com.lv1.hunter.air51test`.
- AIR SDK: `D:\Tool\AIRSDKs\AIRSDK_51.4.1`.
- Android SDK: `D:\Tool\AndroidSdk`, platform API 36; build tools 35 were installed by the AIR build.
- Java 17 is required for this build; Java 25 caused Gradle 8.13 to fail with `Unsupported class file major version 69`.
- Gradle 8.13 was already installed at `D:\Tool\gradle-8.13` and seeded into the Wrapper cache. The build then completed.
- The test descriptor uses `minSdkVersion=19`, `targetSdkVersion=28`, and packages `armeabi-v7a`.
- APK signature verification succeeded with v1 and v2 schemes.

## Generated local artifacts

These files currently live outside the repository in `C:\Users\ssm\Documents\Codex\2026-10-20\ban\outputs`:

- `552114-android16-compatible-sdk28.apk`: earlier SDK 28 compatibility build; retained as a local fallback.
- `552114-air51-android16-test.apk`: AIR 51 build with the original package identity; not installed over the prior package.
- `552114-air51-android16-side-by-side.apk`: AIR 51 build with a separate package identity; installed and launched for the Android 16 test.
- `installed-before-air51.apk`: pulled from the phone before uninstalling the old package; SHA-256 `6736AF60F6544EF2E5538325B3EB54B4B26784032355FA440C2A056CFB99DA06`, matching the SDK 28 compatibility APK.
- `air51-launch.png`: device screenshot showing the game's connection-timeout screen.

The old package was uninstalled once at the user's request, then restored from the pulled APK. Uninstalling cleared its private app data; the APK backup does not restore that data. The old package and the AIR 51 side-by-side test package are both currently installed.

The AIR 51 packaging inputs are copied into `client/air51-repack/` in this repository. The original APK and generated APKs remain outside Git.

## Current blockers

- The original game service is unavailable, so the client cannot pass its connection screen.
- The SWF reveals request names and endpoints, but exact serialization, signatures, response structures, and state transitions still need to be recovered.
- No packet capture or reliable request/response transcript exists yet.
- Core gameplay and persistence have not been tested.

## Safety and scope

This work is for one user's private offline use. Keep the original APK unchanged; use working copies. Do not publish APKs/assets, expose a public service, or commercialize the result. Do not include signing credentials in Git.
