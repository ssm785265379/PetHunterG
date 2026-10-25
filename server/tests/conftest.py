"""Suite-wide fixtures.

Kept in conftest.py so every test module (including the new per-topic files that
lanes add) gets the same deterministic encounters without importing test_app.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _deterministic_encounters(monkeypatch):
    """Turn the random elite encounter off unless a test asks for it.

    Elite fights double the payout (LOCAL_ELITE_REWARD_MULT), so a test that checks
    an exact reward figure would fail roughly one run in seven. Tests that care
    about elites assign the attribute themselves and restore it afterwards.
    """
    from pet_hunter_server import app as _app

    monkeypatch.setattr(_app, "LOCAL_ELITE_CHANCE", 0.0, raising=False)
    # 探险现在按 events/eventProbability 抽事件（约 43% 是非战斗）。
    # 测试默认钉成"战斗"，需要休整/灾难的用例自己 monkeypatch。
    monkeypatch.setattr(_app, "_explore_roll_event", lambda gid: 1, raising=False)
