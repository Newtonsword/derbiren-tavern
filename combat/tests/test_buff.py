"""Buff 系统测试 (匹配实际 API)"""
import pytest
from combat.buff import (
    BuffDef, BuffInstance, BuffManager, TriggerType, AtomicAction,
    PASSIVE_LIBRARY
)


class TestBuffDefinition:
    def test_create_basic_buff(self):
        b = BuffDef(name="STR+3", trigger=TriggerType.PASSIVE,
                     action=AtomicAction.MODIFY_STAT, value=3.0,
                     target="self", description="力量永久+3")
        assert b.name == "STR+3"
        assert b.trigger == TriggerType.PASSIVE
        assert b.action == AtomicAction.MODIFY_STAT
        assert b.value == 3.0
        assert b.max_stacks == 1
        assert b.duration == 0.0

    def test_timed_buff(self):
        b = BuffDef(name="中毒", trigger=TriggerType.ON_TICK,
                     action=AtomicAction.DEAL_DAMAGE, value=5.0,
                     duration=10.0, interval=1.0)
        assert b.duration == 10.0
        assert b.interval == 1.0

    def test_probabilistic_buff(self):
        b = BuffDef(name="麻痹", trigger=TriggerType.ON_ATTACK_HIT,
                     action=AtomicAction.STUN, value=2.0,
                     duration=3.0, chance=0.3)
        assert b.chance == 0.3


class TestBuffInstance:
    def test_create_instance(self):
        bd = BuffDef(name="测试", trigger=TriggerType.PASSIVE,
                     action=AtomicAction.MODIFY_STAT, value=5)
        inst = BuffInstance(definition=bd, remaining=0, source_id="char_1")
        assert inst.name == "测试"
        assert inst.stacks == 1
        assert not inst.expired  # 被动不过期

    def test_expired_detection(self):
        bd = BuffDef(name="限时", trigger=TriggerType.ON_TICK,
                     action=AtomicAction.DEAL_DAMAGE, value=3, duration=5.0)
        inst = BuffInstance(definition=bd, remaining=0, source_id="char_1")
        assert inst.expired


class TestBuffManager:
    def test_apply_new_buff(self):
        mgr = BuffManager("fighter_1")
        bd = BuffDef(name="STR+5", trigger=TriggerType.PASSIVE,
                     action=AtomicAction.MODIFY_STAT, value=5)
        mgr.apply(bd, "self")
        assert len(mgr.buffs) == 1

    def test_stack_same_buff(self):
        mgr = BuffManager("fighter_1")
        bd = BuffDef(name="可叠层", trigger=TriggerType.PASSIVE,
                     action=AtomicAction.MODIFY_STAT, value=2, max_stacks=3)
        mgr.apply(bd, "self")
        mgr.apply(bd, "self")
        mgr.apply(bd, "self")
        assert len(mgr.buffs) == 1
        assert mgr.buffs[0].stacks == 3

    def test_stack_cap(self):
        mgr = BuffManager("fighter_1")
        bd = BuffDef(name="叠满", trigger=TriggerType.PASSIVE,
                     action=AtomicAction.MODIFY_STAT, value=2, max_stacks=3)
        for _ in range(5):
            mgr.apply(bd, "self")
        assert mgr.buffs[0].stacks == 3

    def test_get_stat_mod_by_name_match(self):
        """get_stat_mod 通过 buff 名称匹配 stat (name 必须包含 stat 名)"""
        mgr = BuffManager("fighter_1")
        # 名称需包含 "STR" 才能被 get_stat_mod("STR") 匹配
        bd_str = BuffDef(name="STR+5", trigger=TriggerType.PASSIVE,
                         action=AtomicAction.MODIFY_STAT, value=5)
        bd_end = BuffDef(name="END+3", trigger=TriggerType.PASSIVE,
                         action=AtomicAction.MODIFY_STAT, value=3)
        mgr.apply(bd_str, "self")
        mgr.apply(bd_end, "self")
        assert mgr.get_stat_mod("STR") == 5.0
        assert mgr.get_stat_mod("END") == 3.0
        assert mgr.get_stat_mod("SPD") == 0.0

    def test_tick_removes_expired(self):
        """tick() 会自动清除过期 buff"""
        mgr = BuffManager("fighter_1")
        bd = BuffDef(name="短暂", trigger=TriggerType.ON_TICK,
                     action=AtomicAction.DEAL_DAMAGE, value=1, duration=0.1)
        mgr.apply(bd, "self")
        assert len(mgr.buffs) == 1
        # tick 超过 duration → 过期清除
        mgr.tick(0.2)
        assert len(mgr.buffs) == 0

    def test_get_passive_value(self):
        mgr = BuffManager("fighter_1")
        bd = BuffDef(name="格挡强化", trigger=TriggerType.PASSIVE,
                     action=AtomicAction.BLOCK_MULTIPLIER, value=0.2)
        mgr.apply(bd, "self")
        val = mgr.get_passive_value(AtomicAction.BLOCK_MULTIPLIER)
        assert val == 0.2


class TestPassiveLibrary:
    def test_iron_wall_exists(self):
        assert "铁壁" in PASSIVE_LIBRARY
        buffs = PASSIVE_LIBRARY["铁壁"]
        assert len(buffs) > 0

    def test_berserk_exists(self):
        assert "狂暴" in PASSIVE_LIBRARY
        buffs = PASSIVE_LIBRARY["狂暴"]
        dmg_buffs = [b for b in buffs if b.action == AtomicAction.DAMAGE_MULTIPLIER]
        assert len(dmg_buffs) > 0

    def test_regeneration_exists(self):
        assert "再生" in PASSIVE_LIBRARY
        buffs = PASSIVE_LIBRARY["再生"]
        heal_buffs = [b for b in buffs if b.action == AtomicAction.HEAL_HP]
        assert len(heal_buffs) > 0

    def test_night_vision_exists(self):
        assert "夜视" in PASSIVE_LIBRARY

    def test_lone_wolf_exists(self):
        assert "孤狼" in PASSIVE_LIBRARY

    def test_wolf_pack_exists(self):
        assert "狼群本能" in PASSIVE_LIBRARY

    def test_hard_skin_exists(self):
        assert "硬皮" in PASSIVE_LIBRARY

    def test_eagle_eye_exists(self):
        assert "鹰眼" in PASSIVE_LIBRARY

    def test_all_passives_are_buffdefs(self):
        for name, buffs in PASSIVE_LIBRARY.items():
            assert isinstance(buffs, list), f"{name} 不是列表"
            for b in buffs:
                assert isinstance(b, BuffDef), f"{name} 包含非 BuffDef: {type(b)}"


class TestConditionField:
    def test_condition_field(self):
        b = BuffDef(name="低血狂暴", trigger=TriggerType.ON_LOW_HP,
                     action=AtomicAction.DAMAGE_MULTIPLIER, value=0.5,
                     condition="hp_below_30%")
        assert b.condition == "hp_below_30%"

    def test_stat_condition(self):
        b = BuffDef(name="STR+5", trigger=TriggerType.PASSIVE,
                     action=AtomicAction.MODIFY_STAT, value=5,
                     condition="stat:STR")
        assert b.condition == "stat:STR"
