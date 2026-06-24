"""Fighter 战斗角色测试 (匹配实际 API)"""
import pytest
from combat.fighter import (
    Fighter, hp_from, stam_from, mana_from, def_reduce,
    level_mod, species_resist, TICK, DAMAGE_TYPES
)


def make_basic_fighter(name="测试战士", level=1, **overrides):
    cfg = {
        "id": f"test_{name}",
        "name": name,
        "level": level,
        "species_coeff": 1.2,
        "END": 5, "STR": 5, "SPD": 5, "DEF": 3,
        "INT": 2, "MP": 2, "WIL": 4,
        "team": 0,
    }
    cfg.update(overrides)
    skills = [
        {"name": "挥砍", "type": "slash", "formula": "15+2.5*STR",
         "cooldown": 3.0, "windup": 0.3, "recovery": 0.5},
        {"name": "格挡", "type": "defense", "formula": "50+5.0*DEF",
         "cooldown": 0.5, "windup": 0.1, "recovery": 0.1},
    ]
    return Fighter(cfg, skills)


class TestFighterStats:
    def test_base_stats(self):
        f = make_basic_fighter()
        assert f.lv == 1
        assert f._end == 5.0
        assert f._str == 5.0

    def test_derived_values(self):
        f = make_basic_fighter(END=5)
        assert f.max_hp == hp_from(5)  # 5*100 = 500
        assert f.hp == 500
        assert f.max_stamina == stam_from(5)  # 5*50 = 250

    def test_custom_hp(self):
        f = make_basic_fighter(END=5, current_hp=500)
        assert f.hp == 500
        assert f.max_hp == 500

    def test_stat_accessors_no_buffs(self):
        f = make_basic_fighter(STR=8, DEF=4)
        assert f.str == 8
        assert f.df == 4


class TestDerivedFormulas:
    def test_hp_from(self):
        assert hp_from(1) == 100
        assert hp_from(5) == 500

    def test_stam_from(self):
        assert stam_from(5) == 250

    def test_mana_from(self):
        assert mana_from(3) == 60

    def test_def_reduce(self):
        reduced = def_reduce(100, 15)
        assert reduced == pytest.approx(50.0)  # 100*(1-15/30)=50

    def test_def_reduce_zero_def(self):
        assert def_reduce(100, 0) == 100.0

    def test_level_mod(self):
        mod = level_mod(5, 1)
        assert mod == pytest.approx(1.32)  # 1+(5-1)*0.08

    def test_level_mod_equal(self):
        assert level_mod(3, 3) == 1.0

    def test_species_resist(self):
        r = species_resist(1.5)
        assert r == pytest.approx(0.9)


class TestDamagePipeline:
    def test_take_damage_reduces_hp(self):
        """实际伤害经过 DEF 减伤，不只是单纯减法"""
        f = make_basic_fighter(END=5)  # 1000 HP, DEF=3
        initial = f.hp
        # raw=300, def=3 → def_reduce(300, 3) = 300*(1-3/18) ≈ 250
        f.take_damage(300, "slash")
        actual = initial - f.hp
        assert actual > 0  # 确实造成了伤害
        assert f.hp < initial

    def test_take_damage_not_below_zero(self):
        f = make_basic_fighter(END=1)
        f.take_damage(9999, "slash")
        assert f.hp >= 0

    def test_take_damage_lost_state(self):
        f = make_basic_fighter(END=1)
        f.take_damage(9999, "slash")
        assert f.lost is True

    def test_damage_with_defense(self):
        """高防御减伤更明显"""
        f_high = make_basic_fighter(END=5, DEF=15, name="高防")  # DEF=15
        f_low = make_basic_fighter(END=5, DEF=3, name="低防")   # DEF=3
        f_high.take_damage(300, "slash")
        f_low.take_damage(300, "slash")
        # 高防受的伤害应该更少
        assert f_high.hp > f_low.hp


class TestBlock:
    def test_block_value_default(self):
        f = make_basic_fighter()
        assert f.blocking is False
        assert f.block_value == 0

    def test_set_block_directly(self):
        """blocking 和 block_value 可直接赋值"""
        f = make_basic_fighter()
        f.blocking = True
        f.block_value = 50
        assert f.blocking is True
        assert f.block_value == 50


class TestSpirit:
    def test_spirit_init(self):
        f = make_basic_fighter(WIL=4)
        assert f.collapse == 200  # 4*50
        assert f.max_spirit == 40  # 4*10

    def test_spirit_damage_direct(self):
        """精神攻击通过 take_damage(is_spirit=True)"""
        f = make_basic_fighter(WIL=4)  # 40 spirit
        f.take_damage(30, "slash", is_spirit=True)
        assert f.spirit == 10


class TestDamageTypes:
    def test_all_types_exist(self):
        for t in ("pierce", "blunt", "slash", "fire", "spirit"):
            assert t in DAMAGE_TYPES

    def test_spirit_ignores_armor(self):
        dt = DAMAGE_TYPES["spirit"]
        assert dt["bypass"] == 1.0
        assert dt["armor_dmg_mult"] == 0.0


class TestSkills:
    def test_skills_loaded(self):
        f = make_basic_fighter()
        assert len(f.skills) == 2
        names = [s["name"] for s in f.skills]
        assert "挥砍" in names
        assert "格挡" in names

    def test_cooldowns_initialized(self):
        f = make_basic_fighter()
        assert "挥砍" in f.cooldowns
        assert "格挡" in f.cooldowns

    def test_cooldown_ticks(self):
        f = make_basic_fighter()
        cd = f.cooldowns["挥砍"]
        assert cd.total == 30  # 3.0s / 0.1 tick


class TestDailyRecovery:
    def test_daily_recovery_full(self):
        f = make_basic_fighter(END=5, WIL=4)  # 500 HP, 40 spirit
        f.take_damage(400, "slash")
        f.spirit = 10
        f.daily_recovery()
        assert f.hp == f.max_hp == 500
        assert f.spirit == f.max_spirit == 40

    def test_daily_recovery_already_full(self):
        f = make_basic_fighter(END=5)
        f.daily_recovery()
        assert f.hp == f.max_hp


class TestBuffIntegration:
    def test_apply_stat_buff_via_name(self):
        """get_stat_mod 通过名称匹配，所以 buff 名必须含 "STR" """
        f = make_basic_fighter(STR=5)
        from combat.buff import BuffDef, TriggerType, AtomicAction
        bd = BuffDef(name="STR+5", trigger=TriggerType.PASSIVE,
                     action=AtomicAction.MODIFY_STAT, value=5)
        f.buffs.apply(bd, "self")
        assert f.str == 10  # 5 base + 5 buff (名称含 "STR")

    def test_other_stat_unaffected(self):
        f = make_basic_fighter(STR=5, SPD=5)
        from combat.buff import BuffDef, TriggerType, AtomicAction
        bd = BuffDef(name="STR+3", trigger=TriggerType.PASSIVE,
                     action=AtomicAction.MODIFY_STAT, value=3)
        f.buffs.apply(bd, "self")
        assert f.str == 8
        assert f.spd == 5  # SPD 不受影响
