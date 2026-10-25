# 任务看板

更新时间：2026-10-25 · 规则见 [AGENTS.md](../AGENTS.md)

**"你要？"列由用户填**：`√` 做 / `×` 不做 / `?` 以后再说。没勾的任务不开工。
状态：`待确认` → `排队` → `进行中（lane X）` → `待合并` → `done`

## 一、一览

| ID | 任务 | 类型 | 依赖 | lane / 端口 | 你要？ | 状态 |
|---|---|---|---|---|---|---|
| T01 | 桌面多窗口 + 截图流水线（按 lane 起窗口 / 抓图归档） | 工具 | — | main | √ | **done** `55d1a1c` |
| T02 | lane 脚手架（worktree + 服务 + UI + 存档一键起停） | 工具 | T01 | main | √ | **done** `403a7fb` |
| T03 | 并行友好重构（测试 helper 进 conftest + 路由表化） | refactor | — | main | √ | **done** `5f20884`（179 passed） |
| T04 | 阶段 2：人物成长（等级/经验/属性/称号/转职） | 后端 | — | b1 / 8081 | √ | **done** 8+2 提交已合入（`8e847fe` / `1c56e82` / `751ee95`），**198 passed** |
| T05 | 阶段 3：宠物数值 / 技能 / PvP **规格**（只写文档） | 设计 | — | b2 / b4 / b5 | √ | **done** v3 + §4 技能段已合入（`45365b1` / `eb0ed92`）；只差你定「合成是否重抽属性」A/B |
| T06 | 国王战 109–113 | 后端 | T04（共用属性口径） | b1 / 8081 | | 待 T04 合并后 |
| T07 | 公会首领战 93 | 后端 | T04 | b2 / 8082 | | 待 T04 合并后 |
| T08 | 领奖闭环：81 擂台 / 108 成就 / 107 图鉴内容 | 后端 | — | b1 / 8081 | | 暂缓 |
| T09 | 社交补齐：41 / 53 / 54 / 56 称号 | 后端 | — | b2 / 8082 | | 暂缓 |
| T10 | 内购 / 兑换码 1004–1006、300 | 后端 | — | — | × | **不做**（保持明确报错） |
| T11 | 桌面复验挂起项（开蛋弹窗 / 417 提示 / 扩建证书） | 验收 | T01 | main + [main] | √ | **进行中**（等你操作） |
| T12 | 客户端补丁：图鉴居中、HireListUI 点击、字号溢出 | 客户端 | T01 | c1 / 8081 | | 暂缓 |
| T13 | 本地存档冷备 + 7 天轮转 | 运维 | — | main | | 暂缓 |
| T14 | 仓库清理：`.tmp_*.png`、`_acl-recovery/`、过期 README | 清理 | — | main | | 暂缓 |

---

## 二、并行地基

### T01 桌面多窗口 + 截图流水线

- **目标**：一条命令起**某个 lane 的** ADL 窗口（端口、标题、构建目录都可指定），再一条命令按标题截图归档；
  多个窗口能同时开着，用户直接在对话里看图判断，不用碰手机。
- **结果（done）**：`dev-desktop.ps1` 现在按 lane 起窗口：`-Label`（标题 `PetHunterG preview [b1]`）、`-Port`
  （改写 SWF 服务基址）、`-DevDir`（默认 `build\desktop-dev-<label>`）、`-NoKill`；只重启自己那个窗口（`<DevDir>\adl.pid`），
  不再 `Stop-Process adl64` 误杀别人。每个 lane 用独立 app id —— ADL 按 application id 单实例，同 id 的第二个进程只会
  转发启动然后退出。`preview-shot.ps1` 增加 `-Width/-Height`（150% 缩放下抓到的 960×1440 统一缩回 640×960）。
  实测：[main] 8080 与 [b1] 8081 两个窗口同时存在、各自截图。
- **改动面**：`client/air51-repack/dev-desktop.ps1`
  - `-Port`（改写 SWF 里的服务基址到该端口）
  - `-Label b1`（窗口标题 `PetHunterG preview [b1]`）
  - `-DevDir`（默认 `build\desktop-dev-<label>`，data 目录各自 junction）
  - `-NoKill`（只重启本 lane 的 adl64，不碰别人的窗口）
  - DPI 归一化：抓到非 640×960 时缩放到 640×960 再存盘
- **验收**：`dev-desktop.ps1 -Label main -Port 8080` 与 `-Label b1 -Port 8081` 两个窗口同时存在；
  `preview-shot.ps1 -Title "PetHunterG preview [b1]"` 只抓 b1 那张；两张截图内容对得上各自端口。
- **风险**：低。ADL 多实例本身没问题，风险在"按 lane 精确杀进程"和 DPI 缩放。

### T02 lane 脚手架（服务 + UI + 存档一起管）

- **目标**：`tools/lane.ps1` 一条命令起一个隔离开发环境，服务与 UI 都齐。
- **结果（done）**：`tools/lane.ps1` 已实现 `new/start/shoot/stop/list/remove`；lane 存档在
  `worktrees\<lane>\server\instance\game.sqlite3`（`-CopySave` 复制主库，运行中拒绝覆盖）；端口自动 8081–8089；
  实测 b1(8081) 与 b2(8082) 同时 `/health` 200，互不串库；`stop` 只停该端口与该窗口。
- **命令**：

  ```powershell
  pwsh tools\lane.ps1 new   b1 feat/hero-growth          # 建 worktree + 分支，端口自动取 8081
  pwsh tools\lane.ps1 start b1 [-CopySave] [-NoUi]       # 起 Flask(8081) + ADL 窗口[b1] + /health 检查
  pwsh tools\lane.ps1 shoot b1 -Name bag-popup           # 抓 [b1] 窗口 → docs/preview/日期/b1-bag-popup.png
  pwsh tools\lane.ps1 stop  b1                           # 只停 8081 的 Flask 与 [b1] 窗口
  pwsh tools\lane.ps1 list                               # lane / 端口 / 分支 / 进程 / 存档 / 窗口
  ```

- **改动面**：新增 `tools/lane.ps1`；`docs/desktop-preview.md` 补多 lane 用法
- **验收**：b1(8081) 与 b2(8082) 同时跑，`/health` 各自 ok，两个 ADL 窗口同时在；
  两库互不影响；重复 `start` 幂等（不会起两个实例抢端口 —— 这是本项目已知的坑）；`stop` 不误杀别的 lane。
- **约束**：同时最多 3 个窗口（每个 ADL 约 200MB），第 4 个要先停一个。
- **风险**：中。Windows 上 `SO_REUSEADDR` 会让两个实例抢同一端口，必须按端口精确杀进程；
  `Stop-Process adl64` 会误杀所有窗口，必须按标题/进程树杀。

### T03 并行友好重构（行为零变化）

- **目标**：让两个后端 agent 不再抢同一段代码。
- **做法**：
  1. `server/tests/conftest.py` 暴露 `_create_local_player` / `_envelope` 等 helper，新测试写独立文件；
  2. `/flash.do` 的 `showId` if 链（`app.py:7207–7404`，约 100 行）改成 `{showId: handler}` 路由表；
  3. 只搬移与查表，**不改任何响应**。
- **改动面**：`app.py`（仅路由段）、`server/tests/conftest.py`、`tests/test_app.py`（删 helper 定义）
- **验收**：**175 passed 不变**；`git diff` 只有搬移；新增 1 条"路由表覆盖所有已实现 showId"的断言。
- **风险**：中。动核心路由，必须单独一个提交、先跑全量再改。

---

## 三、后端功能

### T04 阶段 2：人物成长（计划已写好，代码未动）

- **现状**：`players` 没有 `exp/job`；`job` 硬编码 1；`skills`/`buffs` 恒空；`upRole.txt` 120 行未读。
- **依据**：`docs/superpowers/plans/2026-10-24-character-growth.md`（8 个任务，每任务一提交）
  1. `config_tables.up_role_table()` 按 `job` 读 120 行
  2. `players.exp/job` 迁移 + 510 面板返回真实等级/称号/经验
  3. 人物经验曲线 + 自动升级（1–1000）+ 狩猎给人物经验
  4. 探险 / 擂台 / 副本也给人物经验（失败十分之一）
  5. 六维按等级/称号成长，`_role_stats` 成为面板与战斗唯一口径
  6. 人物面板汇总已穿装备技能（`[{id}]`）
  7. 70/71/72 称号列表 / 详情 / 转职（2/3/4 级要 400/600/800 级，5 级起 −999 级）
  8. `server/scripts/grant_hero_exp.py` + 文档
- **验收**：计划内验收清单全绿；桌面截图（人物面板等级/称号/六维、转职页 120 条、等级不够弹 207）；
  老存档（exp=0/job=1）行为不变。
- **风险**：中。改 `_role_stats` 会牵动 6/24/74/103 战斗数值，已有 175 条测试兜底。

### T05 阶段 3：宠物数值 / 技能 / PvP 规格（只写文档，零代码）

- **目标**：把"宠物六维、grows、`pro_*`、星级、世代、性格、技能"怎么进战斗公式定清楚，再动手。
- **产出**：`docs/superpowers/specs/2026-10-25-pet-combat-design.md`
- **必须包含**：配置表列 → 公式映射（`pet.txt` / `grows` / `skill.txt` / `nature.txt`）；
  影响面（6 / 24 / 74 / 103 / 506）；平衡目标与数值量级；分阶段实施顺序；验收用例；
  哪些是 LOCAL DEFAULT、哪些有拆包证据。
- **验收**：文档可被用户直接评审；每条公式都注明来源列；不含代码改动。
- **风险**：低（纯文档）。但**不能**顺手改代码，规格没评审前不动 `app.py`。

### T06 国王战 109–113

- **现状**：5 条命令全未实现，落到兜底空响应。`KingFightInfoUI.as:311+` 需要
  `att/def{png_type,name,img}/index/pic` 的立绘描述。
- **做法**：先拆包取证（列表页字段、确认页、战斗回放结构、排行、奖励）→ 写协议卡片 → 实现 → 测试。
- **验收**：5 条命令都有"客户端消费者 → 响应字段"证据；桌面走通一遍（报名→战斗→结算→排行）；
  新增测试覆盖报名门槛、重复领取、奖励入账。
- **风险**：高（体量最大）。没有证据的字段一律不猜，先写"未实现"。

### T07 公会首领战 93

- **现状**：未实现。`BossListUI.as:151-156` 读 `refresh_time / boss_ap / max_boss_ap` + 列表。
- **做法**：复用 `_fight_payload` / `_battle_side` / `_battle_record` 战斗管线，新增首领血量与次数。
- **验收**：列表渲染、扣次数、战斗结算、奖励与图鉴；桌面截图。
- **风险**：中。依赖 T04 的属性口径，建议 T04 合并后再开。

### T08 领奖闭环：81 / 108 / 107

- **81 擂台奖励领取**：目前只有 82/83 星级周奖，81 未实现。
- **108 成就奖励**：`ArtifactListUI` 的领奖按钮，需要与 107 的条目 id 对齐。
- **107 图鉴列表**：现在返回 `pics: []` 空桩，界面不崩但没内容；用 `pic_unlocked` + `pic.txt` 填真实条目。
- **验收**：三个界面在桌面上有内容、能领取、不能重复领（返回 504）；测试各一条。
- **风险**：低–中。纯补闭环，不引入新玩法。

### T09 社交补齐：41 / 53 / 54 / 56

- **41 玩家更多信息**：现在返回空 `list` 壳，`InfoUI` 只要不崩就不报错。
- **53 好友切磋 / 54 好友酒宴**：`FriendInfoUI` 的按钮，需要资源消耗与战斗结算口径。
- **56 称号**：响应是**逗号分隔裸字符串**（非 JSON），要单独适配；客户端 `TitleUI` / `MainUI` 消费。
- **验收**：按优先级 41 → 53 → 56 → 54；每条都要有客户端消费证据。
- **风险**：中。56 的裸字符串格式容易写错，先拿一条真实消费路径验证再铺开。

### T10 内购 / 兑换码 1004–1006、300 —— 建议不做

- 离线个人服没有计费与 Google Play 回执通道，伪造成功会把存档搞脏。
- **结论**：保持明确报错（现有行为），看板标 `×`，只在文档里写明原因。

---

## 四、桌面 / 客户端

### T11 桌面复验挂起项（不打包，只截图）

- **待复验清单**（handoff 第三节）：
  1. 开蛋 / 开箱宠物弹窗：点空白关闭、右上角 X、多只列出、上下拖动、点宠物进面板返回后弹窗还在；
  2. 背包点素材（强化水晶球 / 奇异口袋 / 红色晶石）弹「该道具不能直接使用」417；
  3. 宠物栏扩建：有证书才让确认，确认后背包 10013 −1；
  4. 道具数量行居中、可点输入、遮罩能挡点击。
- **做法**：主 agent 起 8080 + ADL，逐项截图；用户看图判定，不装 APK。
- **当前进度**：`[main]` 窗口已开（8080，真实存档）。登录/点界面由用户操作；每到一个场景让主 agent 抓一张，
  归档在 `docs/preview/2026-10-25/`，文件名前缀 `T11-`。截图工具：`lane.ps1 shoot main` 不适用（main 不是 lane），
  用 `tools\preview-shot.ps1 -Title "PetHunterG preview [main]" -Name T11-xx -Width 640 -Height 960 -ClientArea`。
- **验收**：每项一张截图 + 一句"预期 vs 实际"；关不掉的项才回去改代码。
- **价值**：能一次关掉 handoff 里"唯一挂起的真机复验项"。

### T12 客户端补丁

- **图鉴文字居中**（`IllustrationTaskUI` 里程碑页文字硬编码 `x=20/120`）—— 先截图确认是哪个界面再改。
- **HireListUI 点击遗留**（已租道具仍发 102，点了没反应）—— 保守改法：函数开头直接发 100 并 return。
- **字号溢出 / 倍速按钮 / BGM 叠加**（后者已修，需复看）。
- **验收**：每个补丁一张桌面截图 + `rebuild-client-patches.py` 的 anchor 断言 `count == 1`。

---

## 五、运维 / 清理

### T13 本地存档冷备

- **目标**：`tools/backup-save.ps1` —— SQLite 冷备（`VACUUM INTO` 或先停服务再复制）、保留 7 天、校验可打开。
- **验收**：备份文件能 `PRAGMA integrity_check`；恢复流程写进 `docs/device-runbook.md`。

### T14 仓库清理

- 根目录 30+ 个 `.tmp_*.png`（已 ignore，但每次 `ls` 很吵）→ 归档到 `docs/preview/_legacy/` 或删除。
- `_acl-recovery/`（沙箱 ACL 诊断产物）→ 加 `.gitignore`。
- `server/README.md` 严重过期（还写 57 tests、说任务/狩猎未实现）→ 按当前实现重写或明确标注"历史文档"。
- `docs/remaining-work.md` 与 `docs/restoration-roadmap.md` 的"未实现"清单已和代码不一致 → 合并进看板后归档。

---

## 六、推荐排期（勾完之后再定）

```text
W0  主 agent（串行）：T01 多窗口截图 → T02 lane 脚手架 → T03 并行友好重构
W1  B1 = T04 人物成长（8081+窗口[b1]） ∥ B2 = T05 宠物规格（纯文档） ∥ 主 agent = T11 桌面复验（8080+[main]）
W2  B1 = T06 国王战（8081+[b1]）       ∥ B2 = T07 公会首领（8082+[b2]） ∥ 主 agent = T12 客户端补丁（c1+[c1]）
W3  B1 = T08 领奖闭环                 ∥ B2 = T09 社交补齐              ∥ 主 agent = T13 → T14
```

排期约束：

- 每波最多 **2 个后端 lane + 1 个客户端 lane**，同时最多 **3 个 ADL 窗口**（8080 / 8081 / 8082）。
- 测试就是在各自的窗口里点：b1 的改动在 `[b1]` 窗口验，b2 的在 `[b2]` 窗口验，互不影响；
  主 agent 逐张截图给用户看，用户判定"没问题"后才进合并门。
- T06 / T07 会复用 T04 引入的 `_role_stats` 与人物等级，**必须等 T04 合并进 main** 再开。
- T08 / T09 互不重叠（命令号与函数都不同），可以同波。
- 同一波里 ADL 窗口与截图由主 agent 串行执行；工作 agent 不启动、不关闭窗口。
- 每波结束：合并门 → 全量测试 → 桌面复看 → 合并进 `main`（你说的 master）→ 删分支与 worktree。

## 七、新任务卡片模板

```markdown
### Txx 标题

- **目标**：
- **依据**（拆包 / 日志 / 用户反馈）：
- **改动面**（文件 + 函数 / 命令号）：
- **验收**（测试 / 截图 / 请求响应）：
- **风险 / 未验证**：
- **lane**：
```

