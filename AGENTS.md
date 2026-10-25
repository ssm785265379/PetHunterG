# AGENTS.md — 开发准则（本仓库所有 agent 必读）

本文件是**协作与验证方式**的唯一准则；提交粒度、回滚等细节见 [docs/dev-workflow.md](docs/dev-workflow.md)，
两者冲突时**本文件的协作规则优先**。

项目：宠物猎人 G 的本地离线服务端（Flask + SQLite）+ AIR 客户端改包。
人只做两件事：**定需求、做真机操作**；其余（代码、测试、桌面预览、合并）由 agent 完成。

## 0. 绝对边界

1. 仅个人本地离线使用：不上传 APK / 游戏资产 / 截图到 GitHub，不公开分发，不运营公网私服。
2. 原始 APK 与 `client/air51-repack/src/**` 视为只读原件；改动只落在副本、补丁脚本和 `build/` 产物里。
3. 凭据、签名私钥、存档 DB、抓包原始件不入库（`.gitignore` 已覆盖，不要 `git add -f`）。
4. `HTTP 200`、单测通过、SQLite 写成功**都不等于**界面可用。没看见画面的，写"未验证"。

## 1. 角色分工

| 角色 | 谁 | 职责 | 明确不做 |
|---|---|---|---|
| **主 agent** | 用户当前会话 | 维护看板、切分支 / worktree、派活、跑合并门、跑桌面预览与截图、写 handoff | 不在功能分支里长期写业务代码（小修正除外） |
| **工作 agent** | `subagent` 派生 | 只在派给自己的 lane 内实现、测试、提交 | 不碰 `main`、不合并、不启动 ADL、不改别的 lane |
| **UI/交互设计 agent** | `subagent` 派生（lane `design/ui-*`） | 出评审清单、评截图、给线框与坐标级改法 | 不写业务代码、不改 AS3、不合并 |

派活必须给全：**分支名 / worktree 路径 / 端口 / 允许改的文件与函数 / 验收命令 / 禁止事项**。

工作 agent 返回必须给：**提交列表 / 测试数字（前→后）/ 未验证项 / 需要主 agent 做视觉验证的步骤**。

## 2. 任务看板

- 唯一任务来源是 [docs/task-board.md](docs/task-board.md)。**用户没勾选的任务不开工。**
- 标为"不做"的任务只允许保持明确报错（例如内购类），不得伪造成功。
- 新冒出来的活先写进看板（ID / 目标 / 改动面 / 验收 / 依赖），再决定谁做。

## 3. 并行开发：一个 lane = 一个任务

> 起因：后端是单文件 `server/pet_hunter_server/app.py`（约 6800 行）+ 单测试文件
> `server/tests/test_app.py`。两个 agent 同时改同一段必然冲突，所以**按 lane 隔离**，
> 冲突只允许发生在合并时，并由主 agent 解决。

### 3.1 建 lane

```powershell
cd F:\git\PetHunterG
git worktree add .worktrees\b1 -b feat/hero-growth main    # 分支：feat|fix|refactor/<模块>-<主题>
```

- worktree 放在仓库内 `.worktrees/<lane>`（沙箱可写、路径短；已加入 `.gitignore`）。
- 工作 agent 的 cwd 是 `.worktrees\b1`，**不是主仓库**。
- 一个 lane 只做看板上的一个任务；做完 → 合并门 → 删分支与 worktree。

### 3.2 端口、存档与窗口隔离

| lane | 端口 | 存档 | ADL 窗口标题 | 桌面构建目录 |
|---|---|---|---|---|
| main（你说的 master，本仓库实际叫 `main`） | 8080 | `server/instance/game.sqlite3`（用户真实存档） | `PetHunterG preview [main]` | `build/desktop-dev-main/` |
| b1 | 8081 | `.worktrees/b1/server/instance/game.sqlite3` | `PetHunterG preview [b1]` | `build/desktop-dev-b1/` |
| b2 | 8082 | `.worktrees/b2/server/instance/game.sqlite3` | `PetHunterG preview [b2]` | `build/desktop-dev-b2/` |
| c1（客户端 lane） | 8081（复用 b1 后端或单独 8083） | 同 b1 / 独立 | `PetHunterG preview [c1]` | `build/desktop-dev-c1/` |

- **同一个 sqlite 文件永远只允许一个服务进程写**。lane 要复现用户存档就**先复制**一份进去，不要指向主库。
- lane 服务只用于协议 / 接口自测，验证完就停。
- **多个 UI 可以同时开**（最多 3 个窗口）：每个 lane 一个 ADL 进程、一个独立构建目录、一个带 lane 名的窗口标题。
  截图按标题精确抓取，互不干扰。工作 agent **不启动 ADL**，窗口与截图统一由主 agent 管。

### 3.3 文件与函数级边界（写进派活单）

派活前主 agent 必须先声明本 lane 的"地盘"，例如：

```text
Lane B1：app.py 的 _job_list/_job_detail/_job_change/_player_payload/_role_stats/_grant_hero_exp、
         config_tables.up_role_table、新增 server/scripts/grant_hero_exp.py；
         允许在 /flash.do 路由链末尾追加 1 行 72 号；测试见 test_app.py 的“人物成长”段。
Lane B2：只写 docs/superpowers/specs/*.md，不动任何 .py。
```

- 新增 `showId` 路由：**只在 if 链末尾追加**（约 `app.py:7400`），不要重排已有行。
- 新增测试：T03 完成后放独立文件 `server/tests/test_<topic>.py`；在此之前追加到 `test_app.py` 末尾，
  并预期合并时有一次尾部冲突。
- 数据库只加 `ALTER TABLE ... ADD COLUMN`，不改既有列的语义。

### 3.4 测试

```powershell
# 工作 agent 在自己的 worktree 里跑；用主仓库的解释器，避免每个 worktree 再建 venv
cd F:\git\PetHunterG\.worktrees\b1\server
F:\git\PetHunterG\server\.venv\Scripts\python.exe -m pytest tests -q
```

基线 **175 passed**（2026-10-25）。数字只允许变大；变小说明有用例被误删，打回。

### 3.5 什么时候可以并行

| 情况 | 结论 |
|---|---|
| 两个后端任务，命令号 / 函数不重叠 | 可并行（B1、B2 各一分支） |
| 都改 `/flash.do` 同一段或同一个函数 | 串行；先做主 agent 的重构任务 T03 |
| 一个后端 + 一个纯文档 / 规格 | 可并行 |
| 一个后端 + 一个客户端补丁 | 可并行（客户端 lane 出 SWF 与截图） |
| 两个客户端 lane 都要看画面 | 可以：每个 lane 一个窗口 + 独立构建目录，标题带 lane；但同时最多 3 个窗口，截图由主 agent 串行抓 |

> 客户端 lane 注意：`build/` 不进 git，新 worktree 要先跑
> `python rebuild-client-patches.py`（约 40 秒）；**不要**跨 worktree 复制 build 产物。

## 4. 合并门（主 agent 逐条勾，缺一条不合并）

> 合并目标分支：本仓库叫 **`main`**（用户口语里的 master 就是它，不要新建 master 分支）。

1. 分支从最新 `main` 切出，`git log --oneline main..<branch>` 里只有本任务的提交。
2. `pytest tests -q` 全绿，数量 ≥ 合并前的数字。
3. 有画面 / 协议证据：截图归档 + 一句"预期 vs 实际"；纯后端给出命令与响应片段。
4. `CHANGELOG.md` 与相关 `docs/` 已更新（改了什么、为什么、怎么验、哪里仍是本地设计）。
5. 没有 `.tmp_*`、`*.apk`、`build/`、DB、凭据混进提交（`git show --stat` 自查）。
6. 有冲突就先解决，再**重跑全量测试** —— 不允许凭"看起来没冲突"合并。
7. **动了 UI / 布局 / 弹窗 / 文案位置**：必须有 UI lane 的评审记录（`docs/design/ui-review.md` 的清单逐条对过，
   截图附在 PR 描述或提交说明里）。UI lane 没签字 = 不合并。

合并方式：

- 提交粒度干净（一修复一提交、信息写根因）→ `git merge --no-ff <branch>`，保留分支轨迹。
- 分支里有多条 WIP 提交 → squash 成一条，信息用最终根因。
- 合并后：全量测试 + 桌面复看一次 → 删分支 / worktree → 看板改 done → 写 handoff。
- 禁止 `push --force` 到 `main`；`origin` 不自动推送，要推必须先问用户。

## 5. 验证顺序：桌面 → 真机

```text
改代码
  └─ pytest 全绿
       └─ 起本 lane 的 Flask（8080/8081/8082…）
            └─ 起本 lane 的 ADL 窗口（640×960，标题带 lane，秒级）
                 └─ 截图归档 + 用户看图判断（多个窗口可同时看）
                      └─ 只有里程碑 / 平台差异才 adt 打包 → 真机
```

- **多服务多窗口**：b1、b2 各起一个 Flask + 一个 ADL 窗口，窗口标题 `PetHunterG preview [b1]` /
  `[b2]`，各自构建目录 `build\desktop-dev-b1\` / `-b2\`；最多同时 3 个窗口。
- **桌面预览**：`client\air51-repack\dev-desktop.ps1`，窗口必须 **640×960**（SWF 原生舞台），
  日志在对应构建目录的 `adl.log` 与 `adl.log.err`。
- **截图归档**：`tools/preview-shot.ps1` 按窗口标题抓 → `docs/preview/<yyyy-MM-dd>/<lane>-<画面>.png`，
  回复里用 `![画面](docs/preview/...)` 内联给用户看。截图是本地审阅产物，不入库。
- 桌面**替代不了**：触屏手势、Android 返回键、系统安装 / 权限弹窗、ARM 渲染差异、性能与发热。
  → 这些和"里程碑验收"才打 APK；打包命令见 [docs/device-runbook.md](docs/device-runbook.md) 与 handoff 第六节。

## 6. 真机调试：用户操作，agent 只读日志

- 安装、点"安装 / 打开"、注册登录、点界面**一律由用户完成**。agent 不代为点击，也不假设已经点过。
- agent 的活是：读 `adb logcat` / 服务端 stdout / `adl.log`，把**请求 → 响应 → 界面**对上，再据此改代码。
  读日志前先说明看哪一段、预期看到什么。
- "截图 + 点击 + 请求分析"只在用户**明确要求**时做。
- 真机结论必须带证据：设备序列号、前台包名、请求 / 响应、界面现象。没证据就写"未验证"。

## 7. 开工 / 收工清单

开工：

- [ ] `git status` 干净？在哪个分支？哪个 lane / 端口？
- [ ] 看板上是哪条任务？改动面（文件 + 函数）写清楚了吗？
- [ ] 预期现象是什么？拿什么验证（测试名 / 截图 / 命令）？

收工：

- [ ] 全量测试数字（前 → 后）
- [ ] 截图或请求 / 响应证据
- [ ] 提交（一修复一提交，信息写根因）
- [ ] 看板状态、`CHANGELOG.md`、相关 `docs/` 更新
- [ ] 未验证项 / 已知风险写清楚

## 8. 必读

1. 本文件 + [docs/dev-workflow.md](docs/dev-workflow.md)（提交与回滚）
2. [docs/handoff-2026-10-25.md](docs/handoff-2026-10-25.md)（当前状态、构建命令、踩坑）
3. [docs/desktop-preview.md](docs/desktop-preview.md)（ADL 预览）
4. [docs/device-runbook.md](docs/device-runbook.md)（真机）
5. 技能 `pethunter-offline-ops`（构建 / 设备 / 交接）
