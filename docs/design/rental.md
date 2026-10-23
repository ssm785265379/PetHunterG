# 探险租赁系统（坐骑 / 装备）

按拆包结果整理的最终规则。所有"本地设计"的数值都标注了来源，可随时调整。

## 一、涉及的界面与命令

| 界面 | 类 | 命令 | 说明 |
|---|---|---|---|
| 租赁商店 | `HireShopUI` | 100 | 列表，`ttype=1` 坐骑 / `ttype=2` 装备 |
| 商品详情 | `HireShopInfoUI` | 101 | 价格、是否已拥有、**租赁按钮** |
| 租赁动作 | `HireShopInfoUI` | 102 | 真正下租 |
| 已租列表 | `HireListUI` | 104 | 九宫格，空格可点开商店 |
| 加槽位 | `HireListUI` | 106 | 购买槽位 |
| 坐骑页 | `HireMountsUI` | 104 | 只取 `list[0]` 作为当前坐骑 |

## 二、定价（来自 `exploreEquip.txt`）

```
id, name, iconId, type, terrain, needMoney, needPoint, needCrystal, effectType, effect, star, remark
```

- `type=1` 是坐骑（7 只），`type=2` 是装备（35 件）
- 价格三选一：`needMoney`（银币）/ `needPoint`（点券）/ `needCrystal`（水晶）
- **没有有效期字段** → 原设计是**永久买断、一次性付费**

## 三、已实现的规则

1. **首次租用**：按表扣费；余额不足回 `not_enough + need_*/own_*`，并写 `RENT_REJECTED` 日志。
   （客户端对失败分支是静默 return，不打日志就完全查不到。）
2. **重复租用**：已拥有的不再收费（同一件不该重复收钱），用于坐骑切换。
3. **坐骑**：可拥有多只，**最近租的那只在用**（`_explore_horse` 取 `explore_rented.id` 最大者）。
   101 对坐骑的 `is_rented` 只表示"是否正在使用"，其它坐骑因此会显示租赁按钮。
4. **装备槽位**：默认 **3** 个（`LOCAL_EXPLORE_DEFAULT_SLOTS`），上限 9。
   上报值取 `min(9, max(3, 已租+1))`——永远留一个可点空格，否则商店入口消失。
5. **替换**：槽位满时租新装备，自动替换**最旧**的一件（先进先出）。

## 四、关键坑（都踩过）

- **`equip_count` 不能等于已租数量**：`HireListUI.as:269-281` 用
  `index < equip_count-1` 决定哪一格可点开商店，等于已租数量时一格可点的都没有，
  商店永久不可达，表现为"装备租赁从来没成功过"。
- **`is_rented=1` 会隐藏租赁按钮**（`HireShopInfoUI.as:196`）。坐骑如果按"拥有"返回，
  7 只全被隐藏 → 没有按钮可点。
- **详情页立绘要 `removeAll()`**：`HireShopInfoUI` 与 `HireMountsUI` 都是直接
  `addChild`，连开几只就叠在一起。
- **客户端没有"取消租赁"**：`EXPLORE_CANCEL_RENT_KEY` 名字叫取消，实际用途是列表；
  所有调用方只传 `{ttype,p,n}`。要做退租必须改客户端。
- **装备页 `HireListUI` 不能用 FFDec 重新编译**：原样导出再导入会报
  `Unknown preprocessor instruction: findproperty`，所以那一页改不了。

## 五、待定（需要玩法口径）

- 槽位解锁是否要消耗道具（现在只按金额，且槽位基本够用）
- 是否需要"替换指定装备"（现在是自动替换最旧）
- 坐骑效果（`effect` 列如 `10:10:10:10:60`）是否要真正作用于探险
