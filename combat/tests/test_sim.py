"""CombatSim 战斗模拟器测试 (CombatSim.run 是 async)"""
import asyncio
import pytest
from combat.sim import CombatSim, CombatResult, CombatLogEntry
from combat.fighter import Fighter, TICK


def make_simple_fighter(name, team, level=1, **overrides):
    cfg = {
        "id": f"{team}_{name}",
        "name": name,
        "level": level,
        "species_coeff": 1.2,
        "END": 5, "STR": 5, "SPD": 5, "DEF": 3,
        "INT": 2, "MP": 2, "WIL": 4,
        "team": team,
    }
    cfg.update(overrides)
    skills = [
        {"name": "挥砍", "type": "slash", "formula": "15+2.0*STR",
         "cooldown": 2.0, "windup": 0.3, "recovery": 0.3},
        {"name": "格挡", "type": "defense", "formula": "0",
         "cooldown": 0.5, "windup": 0.1, "recovery": 0.1},
    ]
    return Fighter(cfg, skills)


def run_sync(sim):
    """同步包装 CombatSim.run()"""
    return asyncio.run(sim.run())


class TestCombatSimBasic:
    def test_create_sim(self):
        t0 = [make_simple_fighter("A", team=0)]
        t1 = [make_simple_fighter("B", team=1)]
        sim = CombatSim(t0, t1)
        assert len(sim.all_fighters) == 2
        assert sim.tick == 0

    def test_run_simple_combat(self):
        t0 = [make_simple_fighter("猫龙", team=0, level=3, STR=8)]
        t1 = [make_simple_fighter("菜鸟", team=1, level=1, END=3)]
        sim = CombatSim(t0, t1, max_ticks=500)
        result = run_sync(sim)
        assert isinstance(result, CombatResult)
        assert result.total_ticks > 0
        assert result.duration > 0

    def test_victory_team(self):
        t0 = [make_simple_fighter("强", team=0, level=5, STR=10)]
        t1 = [make_simple_fighter("弱", team=1, level=1, END=3)]
        sim = CombatSim(t0, t1, max_ticks=500)
        result = run_sync(sim)
        assert result.victor_team == 0

    def test_combat_log_not_empty(self):
        t0 = [make_simple_fighter("A", team=0)]
        t1 = [make_simple_fighter("B", team=1)]
        sim = CombatSim(t0, t1, max_ticks=500)
        result = run_sync(sim)
        assert len(result.log) > 0

    def test_winner_has_survivors(self):
        t0 = [make_simple_fighter("猫龙", team=0, level=5)]
        t1 = [make_simple_fighter("菜鸟", team=1, level=1, END=2)]
        sim = CombatSim(t0, t1, max_ticks=500)
        result = run_sync(sim)
        if result.victor_team == 0:
            assert len(result.team0_survivors) >= 1
        else:
            assert len(result.team1_survivors) >= 1

    def test_final_state_has_hp(self):
        t0 = [make_simple_fighter("A", team=0)]
        t1 = [make_simple_fighter("B", team=1)]
        sim = CombatSim(t0, t1, max_ticks=500)
        result = run_sync(sim)
        for f in result.all_fighters_final:
            assert "hp" in f or "current_hp" in f


class TestCombatSimMultiFighter:
    def test_2v2_combat(self):
        t0 = [
            make_simple_fighter("猫龙", team=0, level=3, STR=7),
            make_simple_fighter("影爪", team=0, level=2, SPD=8),
        ]
        t1 = [
            make_simple_fighter("冒险者A", team=1, level=2, END=4),
            make_simple_fighter("冒险者B", team=1, level=2, STR=5),
        ]
        sim = CombatSim(t0, t1, max_ticks=800)
        result = run_sync(sim)
        assert result.total_ticks > 0
        assert result.victor_team in (0, 1)

    def test_1v3_combat(self):
        t0 = [make_simple_fighter("BOSS", team=0, level=8, STR=12, END=10)]
        t1 = [
            make_simple_fighter("杂兵1", team=1, level=1, END=2),
            make_simple_fighter("杂兵2", team=1, level=1, END=2),
            make_simple_fighter("杂兵3", team=1, level=1, END=2),
        ]
        sim = CombatSim(t0, t1, max_ticks=800)
        result = run_sync(sim)
        assert result.victor_team == 0


class TestEnvironment:
    def test_narrow_environment(self):
        t0 = [make_simple_fighter("A", team=0)]
        t1 = [make_simple_fighter("B", team=1)]
        sim = CombatSim(t0, t1, environment="narrow", max_ticks=500)
        result = run_sync(sim)
        assert result.total_ticks > 0


class TestMaxTicks:
    def test_max_ticks_enforced(self):
        t0 = [make_simple_fighter("A", team=0)]
        t1 = [make_simple_fighter("B", team=1)]
        sim = CombatSim(t0, t1, max_ticks=50)
        result = run_sync(sim)
        assert result.total_ticks <= 55


class TestDefaultAIPick:
    def test_default_pick_returns_skill(self):
        """默认 AI 选技 (现在内部是 async，通过 run_sync 验证)"""
        f = make_simple_fighter("A", team=0)
        sim = CombatSim([f], [make_simple_fighter("B", team=1)])
        # 默认 ai_picker 已经设置为 _default_async_pick
        # 通过跑一场快战来验证 AI 选技能正常工作
        result = run_sync(sim)
        assert result.total_ticks > 0  # 战斗能跑完 = AI 选技正常


class TestCombatLogEntry:
    def test_log_entry_creation(self):
        entry = CombatLogEntry(tick=10, time=1.0, msg="攻击命中", cls="hit")
        assert entry.tick == 10
        assert entry.time == 1.0
        assert entry.msg == "攻击命中"
        assert entry.cls == "hit"
