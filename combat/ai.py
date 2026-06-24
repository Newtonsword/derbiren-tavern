"""
AI 技能选择器 v2 —— 质量分 + 动态调整 + 智力影响 + 距离感知

核心设计:
  1. 战斗开始时为每个技能计算"基础质量分" (基于伤害/前后摇/特殊buff)
     注意: 冷却时间不算入质量
  2. 每 tick 选技时, 根据当前状态动态调整质量分:
      - 低耐力 → 高消耗技能降分
      - 低蓝量 → 高消耗技能降分
      - 低HP → 自疗技能升分
      - 队友低HP → 队友治疗技能升分
      - 敌人护甲类型 → 克制技能升分
      - 距离 → 近战在远处不可用, 远程在近战有惩罚
  3. 智力/等级影响最终选取的精确度:
      - int_ratio = INT / LV
      - ratio越高 → 越倾向于选最高分技能 (小随机扰动)
      - ratio越低 → 选技越随机 (大随机扰动)
      - 随等级提升, 即使蠢角色也会略微变聪明
  4. 防御技能不再可选 —— 由战斗引擎自动触发 (反应式)
"""

from dataclasses import dataclass, field
from typing import Optional
import random

# ══════════════════════════════════════════
# 技能基础质量分 (战斗开始时计算, 不变)
# ══════════════════════════════════════════

@dataclass
class SkillQuality:
    """技能质量分 —— 战斗开始时计算, 持续整个战斗"""
    skill_name: str
    base_quality: float = 50.0        # 基础质量分 (0-100)
    # 构成:
    damage_component: float = 0.0     # 伤害潜力 (0-40)
    speed_component: float = 0.0      # 前后摇速度 (0-30, 越快越高)
    buff_component: float = 0.0       # 特殊效果/治疗/buff (0-30)
    # 技能元数据 (缓存用于动态调整)
    stam_cost: float = 0.0
    mana_cost: float = 0.0
    is_ranged: bool = False
    is_heal: bool = False             # 是否有治疗自身效果
    is_ally_heal: bool = False        # 是否可以治疗队友
    dmg_type: str = "slash"           # 伤害类型 (用于克制判断)
    windup: float = 0.3
    recovery: float = 0.5


def compute_skill_qualities(fighter) -> dict[str, SkillQuality]:
    """
    战斗开始时遍历所有技能, 计算基础质量分。

    质量分构成:
      - 伤害潜力 (0-40): 公式 × 属性估算
      - 前后摇速度 (0-30): windup 短 + recovery 短 = 高分
      - 特殊效果 (0-30): 治疗/增益/减益/控制效果
      (冷却时间不参与质量计算)

    返回: {skill_name: SkillQuality}
    """
    qualities = {}

    for sk in fighter.skills:
        cat = sk.get("category", "")
        stype = sk.get("type", "")

        # 防御技能和被动不参与选技
        if cat == "被动" or stype == "defense":
            continue

        name = sk.get("name", "???")

        # ── 伤害潜力 (0-40) ──
        dmg = _estimate_skill_damage(sk, fighter)
        # 归一化: Lv.1 平均~20, Lv.10 平均~80
        expected_dmg = 20 + fighter.lv * 6
        damage_score = min(40, (dmg / max(expected_dmg, 1)) * 30)

        # ── 前后摇速度 (0-30) ──
        windup = sk.get("windup", 0.3)
        recovery = sk.get("recovery", 0.5)
        total_time = windup + recovery
        # 总时间越短→分越高. 0.5s=满分, 2.0s=0分
        speed_score = max(0, 30 - (total_time - 0.5) * 20)

        # ── 特殊效果 (0-30) ──
        buff_score = _evaluate_buff_effects(sk, fighter)

        base = damage_score + speed_score + buff_score

        # 判断是否治疗技能
        is_heal = any(kw in str(sk).lower() for kw in
                     ['heal', '治疗', '恢复', '治愈', '再生', '回复'])
        is_ally_heal = is_heal and sk.get("target") in ("ally", "all_allies", "team")

        qualities[name] = SkillQuality(
            skill_name=name,
            base_quality=base,
            damage_component=damage_score,
            speed_component=speed_score,
            buff_component=buff_score,
            stam_cost=sk.get("stamina_cost", 0),
            mana_cost=sk.get("mana_cost", 0),
            is_ranged=bool(sk.get("ranged")),
            is_heal=is_heal,
            is_ally_heal=is_ally_heal,
            dmg_type=sk.get("type", "slash"),
            windup=windup,
            recovery=recovery,
        )

    return qualities


def _evaluate_buff_effects(skill: dict, fighter) -> float:
    """评估技能的特殊效果分 (0-30)"""
    score = 0.0
    special = skill.get("special", "")
    effect = skill.get("effect", "")
    desc = skill.get("description", "")
    name = skill.get("name", "").lower()
    all_text = f"{special} {effect} {desc} {name}"

    # 治疗自身
    if any(kw in all_text for kw in ['heal', '治疗', '恢复hp', '恢复生命', '再生', '治愈']):
        score += 15

    # 治疗队友
    if any(kw in all_text for kw in ['治疗队友', '群体治疗', '治愈同伴', 'all_allies']):
        score += 20

    # 护甲相关
    if any(kw in all_text for kw in ['护甲', 'armor', '护盾', '格挡']):
        score += 10

    # 控制效果
    if any(kw in all_text for kw in ['眩晕', 'stun', '硬直', '击退', '打断']):
        score += 18

    # 减益
    if any(kw in all_text for kw in ['减速', '中毒', '燃烧', '破甲', '减防']):
        score += 12

    # 增益
    if any(kw in all_text for kw in ['提升', '增加', '强化', 'buff', '加速']):
        score += 10

    # 多段攻击
    if any(kw in all_text for kw in ['多段', '连击', '多次', 'double']):
        score += 8

    # 范围攻击
    if any(kw in all_text for kw in ['范围', 'aoe', '全体', '溅射']):
        score += 10

    return min(30, score)


# ══════════════════════════════════════════
# 动态质量调整 (每 tick 选技前)
# ══════════════════════════════════════════

def adjust_quality_for_context(
    sq: SkillQuality,
    fighter,
    enemies: list,
    allies: list,
    position_manager=None,
) -> float:
    """
    根据当前战斗上下文调整技能质量分。

    调整因素:
      1. 资源压力: 低耐力/蓝量 → 高消耗技能降分
      2. 生存压力: 低HP → 治疗技能升分
      3. 支援压力: 队友低HP → 队友治疗技能升分
      4. 克制关系: 敌人护甲类型 → 克制技能升分
      5. 距离惩罚: 远程在近战范围 → 降分; 近战在远处 → 不可用

    返回: 调整后的质量分
    """
    score = sq.base_quality

    # ── 1. 资源压力 ──
    if sq.stam_cost > 0 and fighter.stamina > 0:
        stam_ratio = sq.stam_cost / fighter.max_stamina
        if stam_ratio > 0.3:
            # 当前耐力不足够支付 2 次该技能 → 降分
            if fighter.stamina < sq.stam_cost * 2:
                score *= 0.4
            elif stam_ratio > 0.15:
                score *= 0.7

    if sq.mana_cost > 0 and fighter.max_mana > 0:
        mana_ratio = sq.mana_cost / fighter.max_mana
        if mana_ratio > 0.3:
            if fighter.mana < sq.mana_cost * 2:
                score *= 0.4
            elif mana_ratio > 0.15:
                score *= 0.7

    # ── 2. 生存压力 (自身低HP → 治疗升分) ──
    hp_ratio = fighter.hp / fighter.max_hp if fighter.max_hp else 1.0
    if hp_ratio < 0.3 and sq.is_heal:
        score *= 2.5
    elif hp_ratio < 0.5 and sq.is_heal:
        score *= 1.8
    elif hp_ratio < 0.7 and sq.is_heal:
        score *= 1.3

    # ── 3. 支援压力 (队友低HP → 队友治疗升分) ──
    if sq.is_ally_heal:
        for ally in allies:
            if ally.char_id == fighter.char_id or ally.lost:
                continue
            ally_hp_ratio = ally.hp / ally.max_hp if ally.max_hp else 1.0
            if ally_hp_ratio < 0.3:
                score *= 1.8
                break  # 有一个残血队友就足够了
            elif ally_hp_ratio < 0.5:
                score *= 1.4

    # ── 4. 敌人护甲/类型克制 ──
    live_enemies = [e for e in enemies if not e.lost]
    if live_enemies:
        # 找最近的敌人
        if position_manager:
            closest = min(live_enemies,
                         key=lambda e: position_manager.distance(fighter, e))
        else:
            closest = live_enemies[0]

        # 钝击克高护甲
        if sq.dmg_type == "blunt" and closest.armor > 30:
            score *= 1.4
        # 刺击克低护甲
        if sq.dmg_type == "pierce" and closest.armor < 10:
            score *= 1.2
        # 精神攻击克高精神
        if sq.dmg_type == "spirit" and closest.spirit > closest.max_spirit * 0.5:
            score *= 1.3

    # ── 5. 距离惩罚 ──
    if position_manager and live_enemies:
        closest = min(live_enemies,
                     key=lambda e: position_manager.distance(fighter, e))
        dist = position_manager.distance(fighter, closest)

        if sq.is_ranged:
            # 远程在近战范围: 命中减半 → 质量降
            if dist <= 2.0:
                score *= 0.35
            # 太远也不行
            elif dist > 30:
                score *= 0.7
        else:
            # 近战在远处: 不可选
            if dist > 2.0:
                return -1.0  # 不可用标记

    return score


# ══════════════════════════════════════════
# 智力/等级影响
# ══════════════════════════════════════════

def apply_int_influence(quality: float, fighter) -> float:
    """
    根据 INT/LV 比率扰动质量分。

    原理:
      - int_ratio = INT / LV
      - 高 ratio (聪明): 扰动小, 倾向于选最优技能
      - 低 ratio (蠢): 扰动大, 选技更随机

    公式:
      randomness = clamp(0.05, 0.5 - int_ratio * 0.15, 0.5)
      最终分 = quality × random(1-randomness, 1+randomness)

    随等级提升: 即使 INT 不变, LV 增大导致 ratio 缩小, 但 randomness
    上限 0.5 意味着不会超过 50% 的随机范围。而且 INT 通常随等级增长,
    所以实际 randomness 变化平缓。
    """
    lv = max(fighter.lv, 1)
    int_ = fighter.int_

    # INT/LV 比率
    int_ratio = int_ / lv

    # 随机范围: 聪明人~5%, 蠢人~50%
    randomness = 0.5 - int_ratio * 0.15
    randomness = max(0.05, min(0.5, randomness))

    # 扰动
    return quality * random.uniform(1.0 - randomness, 1.0 + randomness)


# ══════════════════════════════════════════
# 主入口: 打分制技能选择
# ══════════════════════════════════════════

# 缓存: {char_id: {skill_name: SkillQuality}}
_quality_cache: dict[str, dict[str, SkillQuality]] = {}


def get_or_compute_qualities(fighter) -> dict[str, SkillQuality]:
    """获取或计算技能质量分 (战斗开始时缓存)"""
    if fighter.char_id not in _quality_cache:
        _quality_cache[fighter.char_id] = compute_skill_qualities(fighter)
    return _quality_cache[fighter.char_id]


def clear_quality_cache():
    """清除质量分缓存 (新战斗开始时调用)"""
    _quality_cache.clear()


def scored_pick_v2(
    fighter,
    enemies: list,
    allies: list,
    position_manager=None,
) -> Optional[dict]:
    """
    打分制技能选择 v2 —— 使用质量分 + 动态调整 + 智力影响。

    1. 获取/计算基础质量分
    2. 对每个可用技能做动态调整
    3. 用 INT/LV 扰动
    4. 选最高分

    返回: 选中的技能 dict, 或 None (无可选技能/等待)
    """
    live_enemies = [e for e in enemies if not e.lost]
    if not live_enemies:
        return None

    qualities = get_or_compute_qualities(fighter)

    best_skill = None
    best_score = -999.0

    for sk in fighter.skills:
        name = sk.get("name", "")
        cat = sk.get("category", "")
        stype = sk.get("type", "")

        # 防御/被动不参与选择
        if cat == "被动" or stype == "defense":
            continue

        if name not in qualities:
            continue

        if not fighter.can_use(sk):
            continue

        sq = qualities[name]

        # 动态调整
        adj = adjust_quality_for_context(
            sq, fighter, enemies, allies, position_manager
        )

        # 距离导致不可用
        if adj < 0:
            continue

        # 智力影响
        adj = apply_int_influence(adj, fighter)

        if adj > best_score:
            best_score = adj
            best_skill = sk

    return best_skill


# ══════════════════════════════════════════
# 辅助: 伤害估算
# ══════════════════════════════════════════

def _estimate_skill_damage(skill: dict, fighter) -> float:
    """粗略估算技能伤害 (用于打分, 不执行伤害管线)"""
    formula = skill.get("formula", "")
    if not formula:
        return 30.0

    formula = formula.replace("×", "*").replace(" ", "")
    ns = {
        "END": fighter.end, "STR": fighter.str, "SPD": fighter.spd,
        "DEF": fighter.df, "INT": fighter.int_, "WIL": fighter.wil,
        "MP": fighter.mp,
        "耐力": fighter.end, "力量": fighter.str, "速度": fighter.spd,
        "防御": fighter.df, "智力": fighter.int_, "精神": fighter.wil,
        "法量": fighter.mp,
        "min": min, "max": max, "abs": abs, "round": round,
    }
    try:
        return float(eval(formula, {"__builtins__": {}}, ns))
    except Exception:
        return 30.0


# ══════════════════════════════════════════
# 向后兼容
# ══════════════════════════════════════════

# 旧的 _scored_pick 现在指向新版本 (兼容 CombatSim 的默认 picker)
async def _scored_pick_async(fighter, enemies, allies):
    return scored_pick_v2(fighter, enemies, allies)

# 同步版本
_scored_pick = scored_pick_v2
_fallback_pick = scored_pick_v2


# 保留旧的 build_skill_context (server.py 的 AI 叙述可能用到)
def build_skill_context(fighter, enemies: list, allies: list) -> str:
    """构建发给 AI 的当前局势描述 (用于战斗叙述, 非选技)"""
    lines = []
    lines.append(f"【{fighter.name} Lv.{fighter.lv}】")
    lines.append(f"  HP:{fighter.hp:.0f}/{fighter.max_hp} "
                 f"耐力:{fighter.stamina:.0f}/{fighter.max_stamina} "
                 f"蓝:{fighter.mana:.0f}/{fighter.max_mana} "
                 f"护甲:{fighter.armor:.0f}")
    lines.append(f"  精神:{fighter.spirit:.0f}/{fighter.max_spirit} "
                 f"崩盘:{'是' if fighter.broken else '否'}")

    lines.append(f"  可用技能:")
    for sk in fighter.skills:
        if sk.get("category") == "被动":
            continue
        cd = fighter.cooldowns.get(sk["name"])
        cd_rem = (cd.remaining * 0.1) if cd else 0
        can = fighter.can_use(sk)
        marker = "✅" if can else "❌"
        lines.append(f"    {marker} {sk['name']}({sk.get('type','?')}) "
                     f"冷却:{cd_rem:.1f}s "
                     f"耗耐:{sk.get('stamina_cost',0)} 耗蓝:{sk.get('mana_cost',0)}")

    lines.append(f"\n【敌方】")
    for e in enemies:
        if e.lost:
            lines.append(f"  {e.name} 💀")
        else:
            lines.append(f"  {e.name} HP:{e.hp:.0f}/{e.max_hp} "
                        f"护甲:{e.armor:.0f}")

    lines.append(f"\n【友方】")
    for a in allies:
        if a.char_id == fighter.char_id:
            continue
        lines.append(f"  {a.name} HP:{a.hp:.0f}/{a.max_hp}")

    return "\n".join(lines)


# DeepSeek API picker (保留, 但正常情况下不会调用)
async def deepseek_skill_picker(fighter, enemies, allies,
                                api_key="", model="deepseek-chat") -> Optional[dict]:
    """调用 DeepSeek API 选技 (后备方案, 优先用打分系统)"""
    if not api_key:
        return scored_pick_v2(fighter, enemies, allies)

    import aiohttp
    ctx = build_skill_context(fighter, enemies, allies)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {api_key}"},
                json={"model": model,
                      "messages": [
                          {"role": "system", "content": "选一个技能名返回"},
                          {"role": "user", "content": ctx}],
                      "max_tokens": 20, "temperature": 0.3},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                data = await resp.json()
                skill_name = data["choices"][0]["message"]["content"].strip()
    except Exception:
        return scored_pick_v2(fighter, enemies, allies)

    for sk in fighter.skills:
        if sk["name"] in skill_name or skill_name in sk["name"]:
            if fighter.can_use(sk):
                return sk
    return scored_pick_v2(fighter, enemies, allies)
