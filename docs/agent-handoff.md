# 后继智能体交接入口

整理日期：2026-10-21。本次仅整理资料，未重新安装应用或验证注册登录。

## Part 1：项目与兼容性

实际仓库为 F:/git/PetHunterG，不是当前工作目录 boogoo。原始 APK 保持不变。AIR 3.4 的旧原生依赖导致 Android 16 启动失败；AIR 51.4.1 ARMv7 副本已能启动。iconless 独立诊断包绕过服务器行绘制异常，保留名字和点击。

## Part 2：服务器

Flask 位于 server/，SQLite 为 server/instance/game.sqlite3。已有注册、登录、账号绑定角色、自动登录及初始角色/空任务响应；完整玩法没有实现。保留数据，不删库。历史 20/21 项测试数字有差异，下次现场运行确认。

## Part 3：设备与当前阻塞

最新操作记录为 localusb 旁装包，127.0.0.1:8080 加 ADB reverse，避开变化的 Wi-Fi IP。已到账号界面，但尚无确认的注册提交或账号 /flash.do 请求。注册登录手机闭环未完成。

安装必须点击系统“安装”，完成后点击“打开/进入”。注册必须填写确认密码，和密码一致。先注册确认成功，再登录。不要把旧卸载授权当成所有包都可卸载。

## Part 4：阅读顺序和继续点

1. docs/device-runbook.md：最新设备流程。
2. server/README.md 与实际 app.py：服务启动和现有协议。
3. docs/protocol-modules.md：玩法子模块静态梳理。
4. docs/progress-v1.md：历史证据和被纠正的假设，勿只读早期结论。

先核实设备、前台包、服务版本与 reverse，然后在 UI 完整注册，关联请求/响应，再验证登录和角色持久化。未获得证据前不声明可玩。

## Part 5：可复用技能

已安装技能：C:/Users/ssm/.codex/skills/pethunter-offline-ops/SKILL.md。
其 references/handoff.md 保存分部事实；references/operations.md 保存构建、Flask、ADB/模拟器及诊断流程。调用：$pethunter-offline-ops。

技能不包含账号密码、签名凭据和 APK，也不替代下一次现场状态检查。未执行 Git 提交或推送。
