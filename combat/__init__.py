"""
程序主导战斗引擎 v2 —— 0.1s tick 实时模拟 + 距离/位置系统

程序负责：时间推进、位置管理、命中判定、伤害计算、自动防御、敌方AI
AI 只负责：战斗中角色选哪个技能 (质量分 + 动态调整 + 智力影响)

v2 新增:
  - PositionManager: 距离/移动/风筝/地图边界
  - 质量分系统: 基础分(战斗开始计算) + 动态调整(每tick) + INT/LV扰动
  - 自动防御: 反应式格挡, 不可主动使用
  - 命中 stagger: 被命中后 0.3s 速度减半
  - 远程距离惩罚: 近战范围命中减半 + 前后摇翻倍

移植自 combat-engine (github.com/Newtonsword/combat-engine)
Buff 系统参考 Unity 卡牌游戏架构 (TriggerType → AtomicAction → ActionChain)

使用方式:
    from combat import Fighter, CombatSim, PositionManager

    our_team = [Fighter(fighter_from_tavern_char(c, team=0)) for c in party]
    enemy_team = [Fighter(fighter_from_tavern_char(e, team=1)) for e in enemies]

    sim = CombatSim(our_team, enemy_team, environment="open",
                    ai_skill_picker=make_ai_picker(api_key))
    result = await sim.run()

    # result.victor_team → 0=玩家赢 1=敌方赢
    # result.all_fighters_final → 更新回 session["characters"] 的 HP
    # result.log → 战斗日志 (含距离信息)
"""

from .fighter import Fighter, CombatAction, SkillCD, TICK
from .buff import BuffDef, BuffInstance, BuffManager, TriggerType, AtomicAction, PASSIVE_LIBRARY, get_passive_buffs
from .position import PositionManager, FighterPosition, MAP_SIZES, MELEE_RANGE, RANGED_COMFORT_MIN, RANGED_COMFORT_MAX
from .skill import (
    parse_tavern_skill, parse_tavern_skills, parse_skill_dict,
    fighter_from_tavern_char,
)
from .sim import CombatSim, CombatResult, CombatLogEntry
from .ai import (
    build_skill_context, deepseek_skill_picker,
    scored_pick_v2, _scored_pick, _fallback_pick,
    SkillQuality, compute_skill_qualities, clear_quality_cache,
    adjust_quality_for_context, apply_int_influence,
)
from .equipment_scaling import (
    RewardTier, RARITY_MULT, RARITY_ORDER,
    calc_equipment_score, calc_all_equipment_scores,
    get_reward_tier, get_explore_tier,
    filter_equipment_by_tier, pick_random_equipment,
    get_xp_reward,
)

# 便捷函数: 制作 AI 选技回调 (带 API key)
def make_ai_picker(api_key: str = "", model: str = "deepseek-chat"):
    """返回一个 async 回调函数，供 CombatSim 使用"""
    async def picker(fighter, enemies, allies):
        return await deepseek_skill_picker(fighter, enemies, allies, api_key, model)
    return picker

# 便捷函数: 默认 AI (v2 打分系统, 不调 API)
def make_default_picker():
    async def picker(fighter, enemies, allies):
        return _fallback_pick(fighter, enemies)
    return picker

__all__ = [
    "Fighter", "CombatAction", "SkillCD", "TICK",
    "BuffDef", "BuffInstance", "BuffManager", "TriggerType", "AtomicAction",
    "PositionManager", "FighterPosition", "MAP_SIZES",
    "MELEE_RANGE", "RANGED_COMFORT_MIN", "RANGED_COMFORT_MAX",
    "parse_tavern_skill", "parse_tavern_skills", "parse_skill_dict",
    "fighter_from_tavern_char",
    "CombatSim", "CombatResult", "CombatLogEntry",
    "deepseek_skill_picker", "build_skill_context", "scored_pick_v2",
    "_scored_pick", "_fallback_pick",
    "SkillQuality", "compute_skill_qualities", "clear_quality_cache",
    "adjust_quality_for_context", "apply_int_influence",
    "make_ai_picker", "make_default_picker",
    "RewardTier", "RARITY_MULT", "RARITY_ORDER",
    "calc_equipment_score", "calc_all_equipment_scores",
    "get_reward_tier", "get_explore_tier",
    "filter_equipment_by_tier", "pick_random_equipment",
    "get_xp_reward",
]
