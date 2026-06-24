"""
装备效能评分 & 奖励分层系统

装备评分 (power_score):
  score = Σ(stats_bonus) × rarity_mult + skill_bonus + special_bonus
  rarity_mult: common=1, uncommon=1.5, rare=2, epic=3, legendary=4
  skill_bonus: 有装备技能 +2
  special_bonus: 有特殊效果 +1

奖励分层 (按天数):
  Day 1-5   : 入门期 — common only, max_score=4, XP 20-40
  Day 6-10  : 成长期 — common+uncommon, max_score=7, XP 40-60
  Day 11-20 : 中期   — up to rare, max_score=12, XP 60-100
  Day 21-30 : 后期   — up to epic, max_score=20, XP 100-150
  Day 31+   : 大后期 — all rarities, XP 150-250

波次奖励分层:
  Wave 1 : common+uncommon, 2 items, XP 40-60
  Wave 2 : up to rare, 2-3 items, XP 60-100
  Wave 3 : up to rare, 3 items, XP 80-120
  Wave 4+: up to epic, 3 items, XP 100-200
"""

from dataclasses import dataclass
from typing import Optional
import random

# ══════════════════════════════════════════
# 稀有度倍率
# ══════════════════════════════════════════
RARITY_MULT = {
    "common": 1.0,
    "uncommon": 1.5,
    "rare": 2.0,
    "epic": 3.0,
    "legendary": 4.0,
}

RARITY_ORDER = ["common", "uncommon", "rare", "epic", "legendary"]


# ══════════════════════════════════════════
# 装备评分
# ══════════════════════════════════════════

def calc_equipment_score(eq: dict) -> float:
    """
    计算单件装备的效能分。

    score = Σ(|stat_value|) × rarity_mult + skill + special
    """
    # 属性分 (绝对值求和，因为 SPD-1 也是设计代价)
    stats = eq.get("stats_bonus", {})
    stat_sum = sum(abs(v) for v in stats.values())
    secondary = eq.get("secondary_bonus", {})
    stat_sum += sum(abs(v) for v in secondary.values())

    # 稀有度倍率
    rarity = eq.get("rarity", "common")
    mult = RARITY_MULT.get(rarity, 1.0)

    base = stat_sum * mult

    # 技能加分
    if eq.get("skill"):
        base += 2

    # 特殊效果加分
    if eq.get("special"):
        base += 1

    return round(base, 1)


def calc_all_equipment_scores(equipment_pool: list[dict]) -> dict[str, float]:
    """计算所有装备的评分，返回 {eq_id: score}"""
    return {e["id"]: calc_equipment_score(e) for e in equipment_pool}


# ══════════════════════════════════════════
# 天数 → 奖励层级
# ══════════════════════════════════════════

@dataclass
class RewardTier:
    """某天数段的奖励参数"""
    allowed_rarities: list[str]       # 允许的稀有度
    max_equipment_score: float        # 装备评分天花板
    xp_min: int                       # 经验值下限
    xp_max: int                       # 经验值上限
    equipment_count: tuple[int, int]  # 波次奖励装备数量 (min, max)
    monster_prob: float               # 获得魔物概率


def get_reward_tier(day: int, wave: int = 0) -> RewardTier:
    """
    根据天数 + 波次返回奖励层级。

    波次可以突破天数限制——比如 Day 8 日常只能拿 uncommon，
    但打赢 Wave 2 可以解锁 rare。
    """
    # 波次修正: 每一波相当于跳 5 天
    effective_day = day + wave * 5

    if effective_day <= 5:
        return RewardTier(
            allowed_rarities=["common"],
            max_equipment_score=4.0,
            xp_min=20, xp_max=40,
            equipment_count=(1, 2),
            monster_prob=0.25,
        )
    elif effective_day <= 10:
        return RewardTier(
            allowed_rarities=["common", "uncommon"],
            max_equipment_score=7.0,
            xp_min=40, xp_max=60,
            equipment_count=(2, 3),
            monster_prob=0.35,
        )
    elif effective_day <= 20:
        return RewardTier(
            allowed_rarities=["common", "uncommon", "rare"],
            max_equipment_score=12.0,
            xp_min=60, xp_max=100,
            equipment_count=(2, 3),
            monster_prob=0.45,
        )
    elif effective_day <= 30:
        return RewardTier(
            allowed_rarities=["common", "uncommon", "rare", "epic"],
            max_equipment_score=20.0,
            xp_min=100, xp_max=150,
            equipment_count=(2, 3),
            monster_prob=0.55,
        )
    else:
        return RewardTier(
            allowed_rarities=["common", "uncommon", "rare", "epic", "legendary"],
            max_equipment_score=99.0,
            xp_min=150, xp_max=250,
            equipment_count=(3, 4),
            monster_prob=0.65,
        )


# ══════════════════════════════════════════
# 装备过滤 & 天花板检查
# ══════════════════════════════════════════

def filter_equipment_by_tier(pool: list[dict], tier: RewardTier,
                             equipment_scores: dict[str, float] = None) -> list[dict]:
    """
    根据奖励层级过滤装备池。
    按稀有度 + 评分天花板双重过滤。
    """
    result = []
    for e in pool:
        rarity = e.get("rarity", "common")
        if rarity not in tier.allowed_rarities:
            continue
        # 评分天花板
        if equipment_scores:
            score = equipment_scores.get(e["id"], calc_equipment_score(e))
            if score > tier.max_equipment_score:
                continue
        result.append(e)
    return result


def pick_random_equipment(pool: list[dict], tier: RewardTier,
                          equipment_scores: dict[str, float] = None,
                          count: int = None) -> list[dict]:
    """
    从过滤后的装备池中随机选择 count 件。
    尽量不重复 slot (武器/防具/饰品各一件)。
    """
    filtered = filter_equipment_by_tier(pool, tier, equipment_scores)
    if not filtered:
        return []

    if count is None:
        count = random.randint(*tier.equipment_count)
    count = min(count, len(filtered))

    # 按 slot 分组，尽量各拿一件
    by_slot = {"weapon": [], "armor": [], "accessory": []}
    for e in filtered:
        slot = e.get("slot", "weapon")
        if slot in by_slot:
            by_slot[slot].append(e)

    picked = []
    slots = ["weapon", "armor", "accessory"]
    random.shuffle(slots)

    for slot in slots:
        if len(picked) >= count:
            break
        if by_slot[slot]:
            item = random.choice(by_slot[slot])
            picked.append(item)
            by_slot[slot].remove(item)

    # 不够的话从剩余随机补
    remaining = [e for e in filtered if e not in picked]
    while len(picked) < count and remaining:
        item = random.choice(remaining)
        picked.append(item)
        remaining.remove(item)

    return picked


# ══════════════════════════════════════════
# 经验值奖励
# ══════════════════════════════════════════

def get_xp_reward(day: int, wave: int = 0) -> int:
    """返回战斗/波次应得的经验值"""
    tier = get_reward_tier(day, wave)
    return random.randint(tier.xp_min, tier.xp_max)


# ══════════════════════════════════════════
# 探索奖励层级
# ══════════════════════════════════════════

def get_explore_tier(day: int) -> RewardTier:
    """
    探索奖励层级 (比波次奖励低一档，因为探索可以每天做)。

    Day 1-10  : common only
    Day 11-20 : common+uncommon
    Day 21-30 : up to rare
    Day 31+   : up to epic
    """
    if day <= 10:
        return RewardTier(
            allowed_rarities=["common"],
            max_equipment_score=3.0,
            xp_min=5, xp_max=15,
            equipment_count=(1, 1),
            monster_prob=0.15,
        )
    elif day <= 20:
        return RewardTier(
            allowed_rarities=["common", "uncommon"],
            max_equipment_score=6.0,
            xp_min=10, xp_max=25,
            equipment_count=(1, 1),
            monster_prob=0.15,
        )
    elif day <= 30:
        return RewardTier(
            allowed_rarities=["common", "uncommon", "rare"],
            max_equipment_score=10.0,
            xp_min=15, xp_max=35,
            equipment_count=(1, 1),
            monster_prob=0.20,
        )
    else:
        return RewardTier(
            allowed_rarities=["common", "uncommon", "rare", "epic"],
            max_equipment_score=18.0,
            xp_min=20, xp_max=50,
            equipment_count=(1, 2),
            monster_prob=0.25,
        )
