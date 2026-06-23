"""
程序主导战斗引擎 —— 0.1s tick 实时模拟

程序负责：时间推进、命中判定、伤害计算、HP/护盾/精神条增减、敌方AI
AI 只负责：战斗中角色选哪个技能

移植自 combat-engine (github.com/Newtonsword/combat-engine)
Buff 系统参考 Unity 卡牌游戏架构 (TriggerType → AtomicAction → ActionChain)

使用方式:
    from combat import Fighter, CombatSim, fighter_from_tavern_char
    
    # 构建双方 Fighter
    our_team = [Fighter(fighter_from_tavern_char(c, team=0)) for c in party]
    enemy_team = [Fighter(fighter_from_tavern_char(e, team=1)) for e in enemies]
    
    # 运行模拟
    sim = CombatSim(our_team, enemy_team, environment="narrow",
                    ai_skill_picker=make_ai_picker(api_key))
    result = await sim.run()
    
    # 写入结果
    # result.victor_team → 0=玩家赢 1=敌方赢
    # result.all_fighters_final → 更新回 session["characters"] 的 HP
    # result.log → 战斗日志
"""

from .fighter import Fighter, CombatAction, SkillCD, TICK
from .buff import BuffDef, BuffInstance, BuffManager, TriggerType, AtomicAction
from .skill import (
    parse_tavern_skill, parse_tavern_skills, parse_skill_dict,
    fighter_from_tavern_char,
)
from .sim import CombatSim, CombatResult, CombatLogEntry
from .ai import build_skill_context, deepseek_skill_picker, _fallback_pick

# 便捷函数: 制作 AI 选技回调 (带 API key)
def make_ai_picker(api_key: str = "", model: str = "deepseek-chat"):
    """返回一个 async 回调函数，供 CombatSim 使用"""
    async def picker(fighter, enemies, allies):
        return await deepseek_skill_picker(fighter, enemies, allies, api_key, model)
    return picker

# 便捷函数: 默认 AI (不调 API，快速模拟)
def make_default_picker():
    async def picker(fighter, enemies, allies):
        return _fallback_pick(fighter, enemies)
    return picker

__all__ = [
    "Fighter", "CombatAction", "SkillCD", "TICK",
    "BuffDef", "BuffInstance", "BuffManager", "TriggerType", "AtomicAction",
    "parse_tavern_skill", "parse_tavern_skills", "parse_skill_dict",
    "fighter_from_tavern_char",
    "CombatSim", "CombatResult", "CombatLogEntry",
    "deepseek_skill_picker", "build_skill_context",
    "make_ai_picker", "make_default_picker",
]
