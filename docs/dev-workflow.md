# 开发流程规矩

这份文档是给"未来的我"看的。起因：还原立绘时同一个功能连改了四次
（overlay → replace → base_only → overlay_no_weapon → replace），中间留了三个
诊断分支，事后看历史像过山车——**问题不在于没提交，而在于改得太碎且没有留下
"为什么"**。

## 铁律

1. **一次修复 = 一次提交。** 改完 → 跑测试 → 立刻 `git commit`，不要攒。
   攒到"一堆改动"再提交，就没法单独回滚某一条。
2. **提交信息写"根因"，不只写"改了什么"。**
   好的例子：
   `fix(养成): 504 只返回在练槽位，空槽留白才可点击选宠——原来 9 格全填满名册，而客户端对有数据的格子禁用点击`
   坏的例子：`fix develop page`
3. **先定位再动手。** 没有证据（反编译代码 / 配置表 / 接口实测 / 真机截图）就不改。
   缺少证据时，**加诊断开关而不是直接改行为**（本次立绘的教训）。
4. **诊断代码要么当场删，要么单独提交并标注 `refactor`/`diag`。**
   不允许把实验分支混进修复提交里。
5. **改完必须跑全量测试**（`server/.venv/Scripts/python.exe -m pytest tests -q`），
   再部署。测试数量只应增加，减少说明有用例被误删。
6. **测试锁行为，不锁实现。** 断言"这个界面需要的字段存在且合理"，
   不要断言"当前这版的具体数字"——否则修复会打挂测试，逼你改测试而不是改对代码。

## 每次改动的固定动作

```powershell
cd server
.\.venv\Scripts\python.exe -m pytest tests -q      # 必须全绿
cd ..
git add -A server
git commit -m "<类型>(<模块>): <根因> —— <做了什么>"
```

真机/线上验证通过后，再单独提交文档（`docs:` / `chore:`）。

## 如何回溯

```bash
git log --oneline -20                          # 最近改动
git log -S'_role_skin_string' --oneline        # 谁改过这个函数
git log -L 1180,1260:server/pet_hunter_server/app.py   # 逐行看某段的演变
git show <sha> --stat                          # 某次提交动了什么
git diff <sha>^ <sha> -- server/               # 某次提交的具体差异
```

## 回滚

```bash
git revert <sha>          # 安全：保留历史，新增一个反向提交
git checkout <sha> -- path # 只把某个文件恢复到某版本（会丢弃该文件未提交改动）
```

**线上服务器**回滚：`server/` 是代码，`/opt/pethunter/instance/game.sqlite3` 是存档，
部署脚本默认保留存档。回滚代码只需 `git revert` 后重新 `tools/deploy-remote.ps1`。

## 诊断开关的用法

有些问题（比如"立绘多了把武器"）不看结果无法定论。这时**加环境变量开关**，
而不是改死代码：

- 服务端读 `os.environ`，用 systemd drop-in 注入：
  `/etc/systemd/system/pethunter.service.d/xxx.conf` → `Environment=KEY=VALUE`
- 用户看一眼就能判定，判定后**当天删掉开关**并提交 `refactor`。

## 提交前自检

- [ ] 全量测试通过，数量没有减少
- [ ] 提交信息能说清"为什么原来错"
- [ ] 没有把 `.tmp_*`、抓包、存档、密钥提交进去（`.gitignore` 已覆盖）
- [ ] 改了服务端 → 已部署并验证；改了 APK → 已重新打包并说明
