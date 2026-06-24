"""
AI 技能选择器 —— 程序战斗时，AI 只负责选技能

每次 Fighter 需要行动时：
  1. 程序传入当前局势 (双方 HP/状态/CD)
  2. 打分系统评估每个可用技能
  3. 程序执行技能计算

打分维度：
  - 伤害潜力 (公式 × 属性)
  - 威胁优先级 (残血敌人、高输出敌人)
  - 防御压力 (敌方正在蓄力→格挡加分)
  - 资源效率 (消耗 vs 预期收益)
  - 崩盘自保 (自身崩盘→防御技权重翻倍)
"""

from typing import Optional
import json
import random


def build_skill_context(fighter, enemies: list, allies: list) -> str:
    """构建发给 AI 的当前局势描述"""
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
                     f"公式:{sk.get('formula','?')} "
                     f"冷却:{cd_rem:.1f}s "
                     f"耗耐:{sk.get('stamina_cost',0)} 耗蓝:{sk.get('mana_cost',0)}")

    lines.append(f"\n【敌方】")
    for e in enemies:
        if e.lost:
            lines.append(f"  {e.name} 💀丧失战斗力")
        else:
            lines.append(f"  {e.name} HP:{e.hp:.0f}/{e.max_hp} "
                        f"护甲:{e.armor:.0f} 精神:{e.spirit:.0f}")

    lines.append(f"\n【友方】")
    for a in allies:
        if a.char_id == fighter.char_id:
            continue
        lines.append(f"  {a.name} HP:{a.hp:.0f}/{a.max_hp} "
                    f"{'崩盘' if a.broken else '正常'}")

    return "\n".join(lines)


SKILL_PICKER_PROMPT = """你是战斗AI。根据局势选择一个技能。

规则:
1. 只返回技能名，不要其他文字
2. 优先击杀残血敌人（HP<30%）
3. 自身崩盘时优先格挡/防御
4. 有精神攻击时优先打精神条高的敌人
5. 体力/蓝量不够的技能不要选
6. 如果所有技能都不可用，返回 "等待"

示例返回:
利爪
扫尾
格挡
等待"""


async def deepseek_skill_picker(fighter, enemies: list, allies: list,
                                api_key: str = "", model: str = "deepseek-chat") -> Optional[dict]:
    """
    调用 DeepSeek API 选择技能
    返回选中的技能 dict，或 None (等待)
    """
    context = build_skill_context(fighter, enemies, allies)

    # 如果没有配置 API key，使用打分 AI
    if not api_key:
        return _scored_pick(fighter, enemies)

    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SKILL_PICKER_PROMPT},
                        {"role": "user", "content": context},
                    ],
                    "max_tokens": 20,
                    "temperature": 0.3,
                },
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                data = await resp.json()
                skill_name = data["choices"][0]["message"]["content"].strip()
    except Exception:
        return _scored_pick(fighter, enemies)

    # 查找匹配的技能
    for sk in fighter.skills:
        if sk["name"] in skill_name or skill_name in sk["name"]:
            if fighter.can_use(sk):
                return sk

    # 没匹配到 → fallback
    if skill_name == "等待":
        return None
    return _scored_pick(fighter, enemies)


# ══════════════════════════════════════════
# 打分式技能选择 (默认 AI)
# ══════════════════════════════════════════

def _scored_pick(fighter, enemies: list) -> Optional[dict]:
    """
    打分制技能选择 —— 比旧版 _fallback_pick 聪明得多。

    对每个可用技能打分，选最高分。考虑：
      1. 伤害潜力 (公式估算)
      2. 敌方蓄力检测 → 格挡加分
      3. 残血斩杀优先级
      4. 资源效率
      5. 崩盘自保
    """
    live = [e for e in enemies if not e.lost]
    if not live:
        return None

    # 检测敌方是否正在蓄力攻击
    enemy_winding = any(
        e.current_action is not None and e.current_action.phase == "windup"
        for e in live
    )

    # 最高威胁敌人 (HP 最低的存活敌人)
    threat_target = min(live, key=lambda e: e.hp)
    threat_hp_ratio = threat_target.hp / threat_target.max_hp if threat_target.max_hp else 1.0

    best_skill = None
    best_score = -999

    for sk in fighter.skills:
        cat = sk.get("category", "")
        stype = sk.get("type", "")
        if cat == "被动":
            continue
        if not fighter.can_use(sk):
            continue

        score = _score_skill(sk, fighter, threat_target, enemy_winding, threat_hp_ratio)

        # 小随机扰动 (±5%) 避免永远选同一个技能
        score *= random.uniform(0.95, 1.05)

        if score > best_score:
            best_score = score
            best_skill = sk

    # 如果没找到攻击技能，尝试防御
    if best_skill is None:
        for sk in fighter.skills:
            if sk.get("type") == "defense" and fighter.can_use(sk):
                return sk

    return best_skill


def _score_skill(skill: dict, fighter, threat, enemy_winding: bool,
                 threat_hp_ratio: float) -> float:
    """
    对单个技能打分 (0-100 分制)

    维度:
      - 伤害潜力: 0-40 分
      - 战术适配: 0-20 分 (格挡时机/斩杀/精神攻击)
      - 资源效率: 0-20 分
      - 技能质量: 0-20 分 (冷却/特殊效果)
    """
    score = 0.0
    stype = skill.get("type", "slash")

    # ── 防御技特殊处理 ──
    if stype == "defense":
        # 敌方蓄力时格挡价值极高
        if enemy_winding:
            return 90.0 + random.uniform(-5, 5)
        # 自身崩盘时格挡
        if fighter.broken:
            return 70.0 + random.uniform(-5, 5)
        # 平时格挡不太需要
        return 15.0 + random.uniform(-3, 3)

    # ── 1. 伤害潜力 (0-40) ──
    dmg = _estimate_skill_damage(skill, fighter)
    # 归一化: 假设 Lv.5 角色平均伤害 ~80
    dmg_score = min(40, dmg * 0.5)
    score += dmg_score

    # ── 2. 战术适配 (0-20) ──
    tactic = 0.0

    # 精神攻击 — 如果目标精神低，更高分
    if stype == "spirit":
        spirit_ratio = threat.spirit / threat.max_spirit if threat.max_spirit else 0
        if spirit_ratio < 0.3:
            tactic += 10  # 斩杀精神
        elif spirit_ratio > 0.7:
            tactic += 5   # 消耗高精神目标
        else:
            tactic += 3

    # 斩杀加分 — 目标残血时攻击技能大幅加分
    if threat_hp_ratio < 0.3:
        tactic += 15
    elif threat_hp_ratio < 0.5:
        tactic += 7

    # 钝击 — 打高护甲目标加分
    if stype == "blunt" and threat.armor > 30:
        tactic += 5
    # 刺击 — 打低护甲目标加分
    if stype == "pierce" and threat.armor < 10:
        tactic += 3

    score += min(20, tactic)

    # ── 3. 资源效率 (0-20) ──
    efficiency = 10.0
    stam_cost = skill.get("stamina_cost", 0)
    mana_cost = skill.get("mana_cost", 0)

    # 耐力够不够
    if fighter.stamina > 0:
        stam_ratio = stam_cost / fighter.stamina if stam_cost else 0
        if stam_ratio > 0.5:
            efficiency -= 5
        elif stam_ratio < 0.2 and stam_cost > 0:
            efficiency += 3

    # 蓝够不够
    if fighter.mana > 0 and mana_cost > 0:
        mana_ratio = mana_cost / fighter.mana
        if mana_ratio > 0.5:
            efficiency -= 3
    elif mana_cost == 0:
        efficiency += 2

    # 自身崩盘时高消耗技能扣分
    if fighter.broken and (stam_cost > 20 or mana_cost > 15):
        efficiency -= 8

    score += max(0, min(20, efficiency))

    # ── 4. 技能质量 (0-20) ──
    quality = 5.0

    # 冷却短的技能多给分 (可以用更多次)
    cd = skill.get("cooldown", 3.0)
    if cd <= 2.0:
        quality += 5
    elif cd <= 4.0:
        quality += 3
    elif cd > 8.0:
        quality -= 2

    # 有特殊效果加分
    special = skill.get("special", "")
    if special:
        quality += 4

    # 前摇短的技能 (不容易被打断)
    windup = skill.get("windup", 0.3)
    if windup <= 0.2:
        quality += 2

    score += max(0, min(20, quality))

    return score


def _estimate_skill_damage(skill: dict, fighter) -> float:
    """
    粗略估算技能伤害 (不实际执行伤害管线，只算原始公式)

    用于打分排序，不需要 100% 精确。
    """
    formula = skill.get("formula", "")
    if not formula:
        return 30.0

    # 统一格式化：× → *，中文属性 → 英文
    formula = formula.replace("×", "*").replace(" ", "")

    # 构建属性命名空间
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


# ── 向后兼容别名 ──
_fallback_pick = _scored_pick
