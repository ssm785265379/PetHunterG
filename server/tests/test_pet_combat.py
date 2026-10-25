"""阶段 3 P1：宠物六维唯一口径 / 相克 / 技能威力 / 怪物真实六维。

规格：docs/superpowers/specs/2026-10-25-pet-combat-design.md
本文件只测公式层（不经过 HTTP），战斗接入的断言在后面的提交里补。
"""

import os

import pytest

from pet_hunter_server import app as A


def _pet_row(**fields):
    """`_pet_stats` 只要求 keys()/下标，普通 dict 就够。"""
    row = {"id": 1001, "lv": 1}
    row.update(fields)
    return row


def test_pet_stats_equals_base_at_level_one():
    # lv1 / 无强化 / 无成长 / 普通性格 → 与 pet.txt 原值完全一致（向后兼容）
    for pet_id in (1001, 5001, 2631):
        base = A._pet_base_stats(pet_id)
        stats = A._pet_stats({"id": pet_id, "lv": 1})
        assert stats == base, f"pet {pet_id} diverged at lv1: {stats} != {base}"


def test_pet_stats_pro_is_additive_not_multiplicative():
    base = A._pet_base_stats(1001)
    stats = A._pet_stats({"id": 1001, "lv": 1, "pro_hp": 1009})
    # 加区：+1009 点，不是 ×2（乘区会让 3★ 火龙变成 27 倍）
    assert stats["hp"] == base["hp"] + 1009


def test_pet_stats_growth_term_is_per_100_levels():
    low = A._pet_stats({"id": 1001, "lv": 1, "gw_hp": 30})
    zero = A._pet_stats({"id": 1001, "lv": 1, "gw_hp": 0})
    assert low["hp"] == zero["hp"], "lv1 时成长不应生效（兼容旧存档）"

    high = A._pet_stats({"id": 1001, "lv": 1000, "gw_hp": 30})
    high_zero = A._pet_stats({"id": 1001, "lv": 1000, "gw_hp": 0})
    assert high["hp"] - high_zero["hp"] == 300, "30 点成长在 1000 级应兑现 300 点"


def test_pet_stats_nature_applies_both_keys():
    plain = A._pet_stats({"id": 1001, "lv": 100})
    # nature 1 = 孤僻：物攻 120% / 物防 80%
    quirky = A._pet_stats({"id": 1001, "lv": 100, "nature": 1})
    assert quirky["phy_att"] == round(plain["phy_att"] * 1.2)
    assert quirky["phy_def"] == round(plain["phy_def"] * 0.8)
    assert quirky["hp"] == plain["hp"]


def test_element_matrix_matches_help8():
    # help.txt 8 原文：每条属性"克 2 / 被 2"，原属性(0)全平
    beats = {1: (2, 6), 2: (3, 4), 3: (1, 5), 4: (1, 6), 5: (2, 4), 6: (3, 5)}
    for attacker in range(0, 7):
        for defender in range(0, 7):
            expected = 1.0
            if attacker and defender:
                if defender in beats.get(attacker, ()):
                    expected = A.LOCAL_ELEMENT_ADVANTAGE
                elif attacker in beats.get(defender, ()):
                    expected = A.LOCAL_ELEMENT_WEAKNESS
            assert A._element_multiplier(attacker, defender) == pytest.approx(expected), (
                attacker, defender
            )


def test_skill_mult_curve():
    assert A._skill_mult(40) == pytest.approx(1.20)
    assert A._skill_mult(100) == pytest.approx(1.50)
    assert A._skill_mult(250) == pytest.approx(2.25)


def test_skill_choices_dedupe_keeps_highest_level():
    # 喷火龙 101:102:5101:5102 = 烈焰之刃 L1+L2、连珠火球 L1+L2
    choices = A._skill_choices("101:102:5101:5102")
    assert len(choices) == 2
    assert {choice["level"] for choice in choices} == {2}
    assert {choice["physical"] for choice in choices} == {True, False}
    # 真·14 族网格：喷火龙两条技能都是火属性
    assert {choice["element"] for choice in choices} == {1}


def test_skill_pick_prefers_counter_over_level():
    attacker = {"phy_att": 52, "mag_att": 52}
    defender = {"phy_def": 52, "mag_def": 52, "element": 3}  # 水属性目标
    high_but_weak = {"id": 103, "family": "烈焰之刃（物理）", "level": 3,
                     "damage": 70, "physical": True, "element": 1}   # 火，被水克
    low_but_counter = {"id": 201, "family": "藤蔓缠绕（物理）", "level": 1,
                       "damage": 40, "physical": True, "element": 2}  # 草，克水
    picked = A._skill_pick([high_but_weak, low_but_counter], attacker, defender)
    assert picked is low_but_counter, "低等级但克制的技能必须赢高等级被克的技能"


def test_monster_uses_its_own_table_stats():
    row = {"hp": 39, "speed": 50, "phy_att": 65, "phy_def": 52,
           "mag_att": 60, "mag_def": 43, "lv": 1, "grows": "5:10"}
    stats = A._monster_stats_from_row(row, reference_lv=1)
    # 表内真值 39/65，再乘 LOCAL_MONSTER_SCALE（默认 0.8）——不是旧曲线的 60/16
    assert stats["hp"] == round(39 * A.LOCAL_MONSTER_SCALE)
    assert stats["phy_att"] == round(65 * A.LOCAL_MONSTER_SCALE)
    assert stats["hp"] != A._monster_stats(1)[0]


def test_damage_k_gives_the_documented_ttk():
    # §3.10：lv1 火龙(L1 技能 ×1.20) 打 lv1 波利(def 52, hp 39) 落在 3.5~4.5 击
    effective = round(52 * A._skill_mult(40))
    swing = A._damage_v2(effective, 52)
    hits = 39 / swing
    assert 3.5 <= hits <= 4.5, f"TTK {hits:.2f} swings"


def test_combat_v2_switch(monkeypatch):
    monkeypatch.delenv("PETHUNTER_COMBAT_V2", raising=False)
    assert A._combat_v2_enabled() is True
    monkeypatch.setenv("PETHUNTER_COMBAT_V2", "0")
    assert A._combat_v2_enabled() is False
