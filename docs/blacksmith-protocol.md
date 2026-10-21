# 铁匠铺命令 32/33/34 协议（本地实现）

## 本地实现状态

已实现一条可验证的本地打造配方：`gid=32001`，消耗 100 金币和 1 个 `11010` 黑铁石，产出装备 `20002` 烈焰之铠。费用、材料与配方属于 LOCAL DEFAULT，不是原服务器数据。成功响应为 `34\t{"index":...,"id":20002,"icon":20002}`；材料不足返回 `-1:400`，货币不足返回 `-1:403`，背包满返回 `-1:300`。事务会原子扣除材料/货币并写入装备库存。

## 结论

- `32` = `GOODS_EXT_LIST_KEY`，拉取铁匠铺列表；`33` = `GOODS_EXT_INFO_KEY`，查询项目详情；`34` = `GOODS_MAKE_KEY`，执行打造（`CommandManager.as:86-92`）。
- 三者默认 POST 到 `flash.do`，参数由 `getCommandPost` 组装，并附加 `type/v/uid?/pwd?/t/sn`（`CommandManager.as:343-430,433-456`）。
- 34 成功响应由主 UI 切换至打造结果页；客户端不在 `MainUI` 检查显式成功标志（`MainUI.as:92-95`）。

## 请求字段

### 32：列表

`BlacksmithListUI.send()`发送 `ttype=data.ttype, loc=0, p=_page, n=9`，命令号即 `showId=32`（`BlacksmithListUI.as:159-169`）。初始页为 1（`BlacksmithListUI.as:40-45`），每页 9 项（`BlacksmithListUI.as:90-105`）。`ttype` 的 1/2/3 对应打造、精炼、附魔标题（`BlacksmithListUI.as:58-73`）。

### 33：详情

打造详情请求为 `ttype=data.ttype, gid=data.gid`（`MakeInfoUI.as:163-169`）。列表点击打造项时，`gid` 来自响应元素的 `id`（`BlacksmithListUI.as:190-202,241-253`）。精炼/附魔分支使用 `index`，但不属于本次打造主路径（`BlacksmithListUI.as:203-215`）。

### 34：打造

打造按钮只发送 `gid=data.gid`（`MakeInfoUI.as:299-302`），未发送 `ttype`。因此无法从客户端确认服务端是否仅凭 gid 唯一确定类型。

## 响应字段

### 32

客户端读取 `param2.list`；每项读取 `index,id,icon,level`，并把 `id`复制为 UI 使用的 `gid`（`BlacksmithListUI.as:219-263`）。空响应处理顺序先访问 `param2.list` 后判断 `!param2`，不能据此可靠推断错误结构（`BlacksmithListUI.as:226-237`）。

### 33

客户端读取 `icon,id,star,pro,hp,phy_att,mag_att,phy_def,mag_def,speed`，可选 `skills`、`buffs`（`MakeInfoUI.as:171-229`）。资源字段为 `need_money/own_money`、`need_point/own_point`、`need_crystal/own_crystal`；`need_goods[]` 元素读取 `id/need_num/own_num`（`MakeInfoUI.as:231-280`）。

### 34 与成功流程

`MainUI`对 34 直接 `flow(CITY_BLACKSMITH_MAKE_RESULT)` 并转交结果页（`MainUI.as:92-95`）。因此源码**无法确认**服务端成功标志（如 `ok`/`success`）及失败响应字段；客户端只是按成功结果结构读取。

`MakeResultUI`读取 `index,id,icon`，可选 `pic`（`MakeResultUI.as:121-139`）；显示产物后，查看按钮以 `index,ttype=3` 请求装备详情（`MakeResultUI.as:142-148`）。结果页初始化时播放成功音效（`MakeResultUI.as:31-38`）。

## 34 成功后的客户端流程

1. 32 返回 `list`；打造项 `id`成为 `gid`。
2. 33 返回产物属性与费用/材料需求。
3. 点击打造，34 只发 `gid`。
4. 响应到达后，`MainUI`切到 `CITY_BLACKSMITH_MAKE_RESULT`。
5. 结果页显示 `id/icon` 对应装备；若有 `pic`则调用 `GameUtil.getPic`。用户点击查看，再发送 `index,ttype=3`。

## 配置中的真实可用 ID

装备表的字段和样本：`20001`烈焰之剑、`20002`烈焰之铠、`20003`烈焰之盔（`client/air51-repack/src/data/zh-CN/config/equip.txt:1-4`）；高阶样本 `67001-67006`（`equip.txt:902-907`）。这些是客户端配置中可显示的装备 ID，当前账号是否可打造仍以命令 32 返回为准。

材料/道具表列出打造材料（`client/air51-repack/src/data/zh-CN/config/prop.txt:1,55-65`）：`11001`烈焰龙之玉、`11002`花魁蛙之玉、`11003`水炮龟之玉、`11004`炽炎兽之玉、`11005`果香龙之玉、`11006`巨力鳄之玉、`11007`烈羽鸟之玉、`11008`乱影蜥之玉、`11009`潮汐怪之玉、`11010`黑铁石；`11200`猎人宝箱碎片备注为可打造超级装备（`prop.txt:81-83`）。这些是静态配置 ID，不代表账号库存或服务端当前允许。
