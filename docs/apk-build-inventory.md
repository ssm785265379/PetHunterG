# APK 构建诊断清点

检查日期：2026-10-21。范围为本地文件和只读工具诊断；本轮没有构建、安装、操作手机或重启服务。手机当前安装包是否与磁盘产物一致，仍由主流程核对。

## 当前可用产物

`client/air51-repack/build/out/PetHunterG-Iconless-LocalUSB.apk` 经 Android SDK 36.0.0 的 aapt 核实：

- 包名 `air.com.lv1.hunter.iconless.localusb`，版本 2.7.3，versionCode 2007003。
- minSdk 19、targetSdk 28；唯一原生 ABI 为 `armeabi-v7a`，不是 ARM64 包。
- 构建描述在 `build/PetHunter-iconless-localusb.xml`，不是根目录版本 2.7.1 的 `PetHunter-app.xml`。清单允许明文 HTTP，入口为 APetHunter.swf。
- apksigner verify 退出码 0，v1/v2 签名有效，单签名者 CN=PetHunterG Local USB；证书 SHA-256 为 `f6a515d0100a548a0df60fdab8d2463e77a534bf522ff2cc30a09cd27f1d1d26`。
- apksigner 同时警告两个 META-INF 构建元数据条目不受 JAR 签名保护；不能把签名验证解释为所有 ZIP 元数据均受 v1 保护。

SHA-256 实测值：

| 文件 | SHA-256 |
| --- | --- |
| LocalUSB APK | `2DB8343BFD23906DC22019DBC64D72F14A29E1AC857881FB035133289553A127` |
| build/input-localusb/APetHunter.swf | `DAFD3F1E9FED018ECF3EA7285B30D5EC99FE605E7AB01D02087AE51F316CDA64` |
| src/APetHunter.swf | `F7FDAC0A82E9BD656AF04501E8E182473F74E1A0240282D70DDBAC50922A10F5` |
| 原包 C:/Users/ssm/Desktop/552114.apk | `1B83DCDFFC9E8B4BBBA5C778030D15005163957AA2B7FE20113E5AF0403FDBD9` |

直接读取 APK 的 assets/APetHunter.swf 所得哈希与 input-localusb 一致。上述结果没有证明手机安装包哈希，也没有回溯证明源 SWF 的历史未改动，只提供当前核对基线。

`build/out` 另保留 LAN/LAN2、LAN3 调试和诊断、Iconless、IPFix 等 APK；`build/input`、input2、input3、input-iconless、input-localusb 是不同工作副本。不要按文件名相近就互换输入。现有签名材料位于忽略的 build 目录；没有读取密钥内容或密码，不应提交它们。

## 工具与补丁

已确认存在 AIR SDK `D:/Tool/AIRSDKs/AIRSDK_51.4.1/bin/adt.bat`、JDK `D:/Configure/jdk17/bin/java.exe`、Android build-tools 35.0.0 与 36.0.0。仅在本次 apksigner 进程上下文设置 JAVA_HOME 为 JDK17，没有修改全局配置。

根目录未发现可复用的一键构建脚本。现有两个 Python 脚本负责局部变换，不负责 ADT 打包：

- `patch_swf_url.py:99`：只接受未压缩 FWS，修改 DoABC 字符串池，重算字符串和 SWF 长度；默认每个旧字符串恰好命中一次，`--replace-all` 才允许多次命中。CLI 支持多组 `--replace OLD=NEW`，不能只改一个常量便认定四个 URL 均已修复。
- `patch_serveritem_iconless.py:17`：处理 FFDec 导出的 ServerItem.as，只去除 data setter 的图标和状态资源查找，验证服务器行名称仍保留。它输出 AS3 文本；仍需经已核实的 FFDec 导入流程才会改变 SWF，不是直接 APK 补丁。

在 air51-repack 目录执行 `server/.venv/Scripts/python.exe -B -m unittest discover -s tests -v`（实际使用解释器绝对路径），6 项测试全部通过。测试验证合成 SWF 的长度/多 URL/重复常量约束及 ServerItem 文本变换；不覆盖真实 SWF 全部结构、ADT 重建或手机界面。

## 后续有实际客户端需求时的验证路径

1. 服务端协议修复先沿用已可启动的 LocalUSB APK，避免无关重打包。
2. 必须改客户端时，新建独立工作副本和描述文件，保留源 APK/SWF 与当前可用 LocalUSB 产物；先确认需改的 AS3 消费者和四个 URL 常量，再运行补丁测试。
3. 用 JDK17 进程环境及现有 AIR SDK；先查询本机 ADT 帮助和既有可靠构建记录，确认目标 ABI、签名材料及密码的安全输入方式。现阶段没有核实可直接复制的完整 ADT 命令，不能猜密码或把凭据写入命令、文档。
4. 打包后重新执行 aapt dump badging、apksigner verify、SHA-256；读取 APK 内 SWF 与工作副本对照，确认新包身份和实际补丁。
5. 安装交由主流程：默认新包名旁装，不卸载、不清数据，观察系统安装确认与打开后的前台包名；重建 ADB reverse 后关联界面、服务器请求和响应。APK 备份不能替代私有存档备份。

32 位系统警告的候选解决方向是 ARM64 构建，但本轮既未构建也未验证，不能用 targetSdk 修改宣称解决。仅限个人本地使用，不上传或分发 APK 和资源。
