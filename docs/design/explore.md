# 探险系统：数据还原与实现差距

按游戏策划视角，从 `exploreMap.txt` / `worldMap.txt` / `exploreEquip.txt` 反推原本的设计，
再对照当前服务端实现，列出差距。**所有规则以配置表为准，"本地设计"处会显式标注。**

## 一、配置表说了什么

`exploreMap.txt` 185 行，关键列：

| 列 | 含义 | 世界1 地图1 的实例 |
|---|---|---|
| `worldId` | 属于哪个世界（`worldMap.txt` 9 个世界） | 1 |
| `terrain` | 地形：1 平原 / 2 草地 / 3 雪地 / 4 沙漠 / 5 火山 | 1 |
| `star` | 评价分档 `1500:1000:700:500` | 同上 |
| `max_days` | 一次探险持续天数（**多数行是空的**） | 空 |
| `needExploreMap` | **前置地图**：必须先完成哪张 | 0（起点） |
| `needDiscoverRate` | 该图需要的**发现率** | 400 |
| `events` / `eventProbability` | 事件池与权重 `11:12:13:14:15` / `5700:2000:500:500:1300` | — |
| `catchPet` | 该图可捕捉的宠物 id（0 = 不可捕捉） | 0 |
| `passRewardPoint/Crystal/Goods` | 通关奖励 | — |
| `maxRewardPoint/...` | 单次收益上限 | — |

世界 1 的链条是严格线性的：
```
图1 (need 0, rate 400) → 图2 (need 1, rate 450) → 图3 (need 2, rate 500) → … → 图10
   → 图11 (need 212, terrain 2, rate 1500)   ← 换地形，明显是"世界1 的下一区域"
   → 图12 (need 11, catchPet 6002)           ← 开始能抓宠
```

**所以"只有一张地图能进"不是 bug，是设计**：起点图中只有 `needExploreMap == 0` 的那张开放，
后续必须靠**发现率**逐张解锁。

## 二、原本的玩法循环

1. 进世界 → 看到该世界的地图链
2. 选一张已解锁的地图 → **派队伍出发**（消耗探险体力 `explore_ap`）
3. 队伍在图上推进，跑**发现率**（`needDiscoverRate` 是这张图的通关线）
4. 过程中按权重随机事件：战斗（57%）、采集、遭遇、宝箱、稀有事件
5. 收益：道具/水晶/银币（受 `maxReward*` 限制）、宠物经验、**可捕捉宠物**（`catchPet`）
6. 发现率达标 → 这张图通关 → **下一张图解锁**；世界最后一张通关 → 下一个世界

坐骑（`exploreEquip` type 1）与探险装备（type 2/3）是**派遣加成**：
坐骑影响行进速度/耗时，装备影响队伍强度与收益。

## 三、当前实现的差距（按严重度）

| # | 差距 | 后果 |
|---|---|---|
| 1 | **发现率不落地**：`now_discover_rate` / `add_discover_rate` 恒为 0，没有持久化 | 永远打不满 `needDiscoverRate` → **永远解锁不了第二张图** → 玩家只看到一张能玩 |
| 2 | **一次性结算**：103 一按就返回结果（`is_finish:1`），没有"出发中/倒计时/收获" | 没有挂机派遣的节奏，点一次就没下文 |
| 3 | **地图列表不带解锁态** | 客户端无法把未解锁的图灰掉（它自己把 `isClick` 硬编码为 true） |
| 4 | **没有派遣队伍概念** | 不选宠、不选坐骑，`energy`/`supply` 都是编的 |
| 5 | 事件恒为战斗 | 探险事件池 5 种只用了 1 种 |

## 四、本轮实现（只做第 1 项）

理由：它是"只有一张图"的直接原因，且不需要客户端改包。

- 新表 `explore_progress(player_id, gid, discover_rate, cleared_at)`
- `103` 胜利后按 `LOCAL DEFAULT` 增加发现率（每场 +100），返回真实的
  `now_discover_rate` / `add_discover_rate` / `need_discover_rate`
- `98` 的每行补 `discover_rate` / `need_discover_rate` / `is_open`：
  `needExploreMap == 0` 或前置图 `discover_rate >= 其 needDiscoverRate` 即开放
- 未解锁的地图调用 `103` 时返回 `-1:100`（客户端会弹提示，而不是静默白跑）

**未做（需客户端改包）**：派遣倒计时、队伍编成、事件多样化、列表灰显。
