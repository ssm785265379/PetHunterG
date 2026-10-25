"""T04 人物成长：等级/经验/称号/属性/装备技能/70-71-72 转职。

新测试一律放这里（T03 之后不再往 test_app.py 尾巴上堆），helper 从 support 取。
配置表数值以 client/air51-repack/src/data 的原始文件为准，本地设计数值在
app.py 里用 LOCAL DEFAULT 标注。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pet_hunter_server import config_tables
from support import create_local_player, envelope


def test_up_role_table_reads_all_hunter_titles():
    rows = config_tables.up_role_table()

    assert len(rows) == 120
    assert sorted(rows) == list(range(1, 121))
    assert rows[2]["needLevel"] == "400"
    assert rows[2]["rewardGoods"] == "10016:1"
    # 5 级转生是第一个掉 999 级的称号；4 级及以前不掉级。
    assert rows[5]["lowerLevel"] == "999"
    assert rows[4]["lowerLevel"] == "0"
    assert rows[1]["rewardGoods"] == "0"


def test_clear_caches_also_drops_the_up_role_table():
    config_tables.up_role_table()
    assert config_tables.up_role_table.cache_info().currsize == 1

    config_tables.clear_caches()

    assert config_tables.up_role_table.cache_info().currsize == 0
