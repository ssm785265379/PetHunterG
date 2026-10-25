# 口播稿 v3：专业版（9 分 09 秒，每句都落到「软件 + 功能 + 结果」）

> 这一版修正 v2 的问题：不再只讲现象，**每一句都说出用哪个软件、做什么操作、得到什么结果**。
> 文件：
> - `restore-apk-voiceover-v3.json` —— 95 句字幕时间轴（同参考稿结构，可直接导入剪辑软件）
> - `restore-apk-voiceover-v3-table.md` —— 时间 / 时长 / 口播 对照表
> - 本文件 —— 工具-功能对照、分段、录制清单、念法
>
> 技术底稿：[restore-old-apk-video-script.md](restore-old-apk-video-script.md)；口语短句版：[restore-apk-voiceover-v2.md](restore-apk-voiceover-v2.md)。

## 一、v3 和 v2 的差别

| | v2 短句流 | **v3 专业版** |
|---|---|---|
| 每句信息量 | 一个现象 | **软件名 + 操作 + 产出** |
| 例 | 「装不上就看 logcat」 | 「用 adb logcat 过滤包名，能看到它缺 libstagefright.so」 |
| 句长 | 4–10 字 | 15–30 字 |
| 时长 | 6:09 / 169 句 | **9:09 / 95 句** |
| 适合 | 短视频、预告 | **正式教程、B 站/YouTube 长视频** |

## 二、工具 → 功能 → 本项目命令（口播里会逐条念到）

| 软件 / 版本 | 具体功能 | 本项目里的操作 | 产出 |
|---|---|---|---|
| **7-Zip** | 备份、查看 zip 结构 | 右键 APK 打开；把原包和存档各压一份 | 可回滚的备份 |
| **apktool** | 解包 APK、回编译资源 | `apktool d 游戏.apk -o out` | `AndroidManifest.xml`、`assets`、`lib`、`res` |
| **FFDec 26.4.0**（JPEXS Free Flash Decompiler） | 反编译 SWF、搜字段、导出/导入 AS3、二进制视图搜字符串 | `-export script` 导出；`-importScript` 回写；Ctrl+F 搜 `param2.list` | AS3 源码、可改的 SWF |
| **HARMAN AIR SDK 51.4.1（adt）** | 用新运行库重打包 APK、签名 | `adt -package -target apk -arch armv7 -storetype pkcs12 ...` | 新 APK |
| **JDK 17** | adt 的运行环境 | 设置 `JAVA_HOME`；25 会报 class file 69 | — |
| **Android SDK build-tools 35（aapt）** | 验证包信息 | `aapt dump badging app.apk` | 包名 / 版本 / 启动 Activity |
| **adb** | 安装、端口转发、日志 | `install -r`、`reverse tcp:8080 tcp:8080`、`logcat` | 装机、日志、隧道 |
| **adl64**（AIR SDK 自带） | 桌面直接跑 SWF，不打包 | `adl64 PetHunter-desktop.xml` | 2 秒出画面 |
| **mitmproxy** | 抓 HTTP、看请求响应 | 手机/模拟器设代理；装它自己的 CA | `POST /flash.do` 的请求与响应 |
| **Python 3.11 + Flask** | 本地协议服务 | `/flash.do`、`/health`、`server.xml` | 协议响应 |
| **SQLite** | 存档、事务、WAL | 账号/角色/背包/宠物表；每写一次一个事务 | 可持久化的存档 |
| **pytest** | 契约测试 | `pytest tests -q` | 测试数字（只增不减） |
| **git / git worktree** | 版本管理、并行隔离 | `worktree add`，一任务一分支一端口 | 可回滚的提交 |
| **PowerShell** | 自动化 | `dev-desktop.ps1`、`lane.ps1`、`preview-shot.ps1` | 一键起窗口 / 起服务 / 截图 |

## 三、分段与画面（95 句）

| 段 | sid | 时间 | 时长 | 口播要点 | 画面必须出现 |
|---|---|---|---|---|---|
| 开场 | 1–5 | 00:00 | 24s | 停服、目标、工具链 | 手机超时 → 电脑能打怪 |
| 工具总览 | 6–14 | 00:25 | 53s | 逐个报软件名与用途 | 桌面摆一排图标/窗口，逐个高亮 |
| 1 解包 | 15–21 | 01:18 | 42s | apktool、7-Zip、assets 里的 SWF | 终端 `apktool d`，资源树，SWF 文件属性 |
| 2 换运行库 | 22–29 | 02:00 | 48s | adb logcat、AIR SDK、adt、签名、aapt | logcat 报错行、adt 命令、aapt 输出 |
| 3 装机 | 30–33 | 03:09 | 23s | adb install、手机点安装、验收标准 | 安装器弹窗、连接超时页（里程碑） |
| 4 桌面预览 | 34–40 | 03:11 | 42s | adl64、mklink 联接、640×960、trace 重定向 | 两秒出窗口；640×960 vs 480×854 对比 |
| 5 抓包 | 41–47 | 03:54 | 42s | FFDec 搜 IP、mitmproxy、flash.do、Tab | 抓包列表、请求体、响应原文（高亮 Tab） |
| 6 服务骨架 | 48–54 | 04:36 | 41s | Flask 路由、空结构、SQLite 事务 | 代码 + 客户端不崩 |
| 7 字段对齐 | 55–61 | 05:17 | 38s | 搜 `param2.list`、消费者、改坏验证 | 左 FFDec 右响应，改一个字段界面空白 |
| 8 错误协议 | 62–69 | 05:55 | 42s | 裸 `-1:300` 被吞 → 加 Tab → 日志 | 无反应 → 弹提示 → `PROTOCOL_ERROR` |
| 9 数值证据 | 70–76 | 06:39 | 41s | 配置表 BOM、列序陷阱、help 矛盾、来源标记 | 三张表并排、证据分级表 |
| 10 存档 | 77–79 | 07:20 | 16s | WAL、事务、退出重进 | SQLite 表 + 重登后数据 |
| 11 客户端补丁 | 80–83 | 07:36 | 24s | importScript、不能新增类、anchor 断言 | FFDec 改类、脚本断言失败演示 |
| 12 工程化 | 84–87 | 08:01 | 23s | 分支/端口/窗口隔离、pytest、合并六门 | 两个 lane 窗口 + 两个服务 + 测试数字 |
| 13 打包 | 88–93 | 08:24 | 35s | adt 签名、adb reverse | 打包命令、装机、`reverse --list` |
| 结尾 | 94–95 | 08:59 | 10s | 证据四件套、免责 | 完整闭环 10 秒 |

## 四、每个工具要录的画面（拍摄清单）

1. **apktool**：终端里 `apktool d` 的输出；资源树展开到 `assets/APetHunter.swf`。
2. **7-Zip**：右键 APK → 打开压缩包 → 看到 `assets/`。
3. **FFDec**：打开 SWF → 左侧类列表 → Ctrl+F 搜 `param2.list` → 高亮到读取那一行；再切「二进制」搜 `http://`。
4. **adb logcat**：过滤包名，停在 `libstagefright.so` 报错那一行。
5. **adt**：完整命令 + 结尾 `APK packaged successfully`。
6. **aapt**：`dump badging` 输出里的 `package: name=... versionName=...`。
7. **adb install**：手机上安装器弹窗 → 打开 → 停在连接超时。
8. **adl64**：双击脚本 → 2 秒窗口出现；旁边放一个「打包 2 分钟」的对比计时。
9. **mitmproxy**：请求列表 → 点开一条 → 请求体三个参数 → 响应体高亮 `\t`。
10. **Flask**：`/flash.do` 代码 10 行 + 终端打印 `showId=22`。
11. **SQLite**：DB Browser 或命令行查 `players` 表；重启后再查一次。
12. **pytest**：`276 passed` 一屏；再故意删一条测试，数字变 275（演示"只增不减"）。
13. **git worktree**：`git worktree list` 两条 + 两个窗口并排。
14. **打包**：adt 命令 + APK 文件属性 + `adb reverse --list`。

## 五、念法（这版的核心）

- 每句结构：**用【软件】做【动作】，得到【结果】**。这三段缺一段，观众就跟不上。
- 软件名第一次出现念全称（FFDec 念「JPEXS Free Flash Decompiler」），之后简称。
- 命令不要逐字符念，念「命令名 + 关键参数」：`adt -package、target apk、arch armv7、带签名`。
- 数字放慢：`43 兆`、`两分钟`、`276 个测试`、`640 乘 960`。
- 每段结尾一句结论，例如「这一步的验收标准只有一个：能进到游戏自己的报错页」。

## 六、30 秒预告（从 v3 抽）

> 1 停服六年 → 2 连接超时 → 3 用 AI 加工具链救活 → 4 能装能进能存档 → 6 解包用 apktool → 7 反编译用 FFDec → 8 重打包用 AIR SDK → 9 装机和日志用 adb → 94 每一步都有证据 → 95 你也可以去救一个

---

**一句话总结这版的改法**：v2 说的是「发生了什么」，v3 说的是「我用什么工具，做了什么，得到了什么」。
