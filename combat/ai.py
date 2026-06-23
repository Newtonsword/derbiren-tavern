"""
AI 技能选择器 —— 程序战斗时，AI 只负责选技能

每次 Fighter 需要行动时：
  1. 程序传入当前局势 (双方 HP/状态/CD)
  2. DeepSeek 返回技能名
  3. 程序执行技能计算
"""

from typing import Optional
import json


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

    # 如果没有配置 API key，使用默认 AI
    if not api_key:
        return _fallback_pick(fighter, enemies)

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
        return _fallback_pick(fighter, enemies)

    # 查找匹配的技能
    for sk in fighter.skills:
        if sk["name"] in skill_name or skill_name in sk["name"]:
            if fighter.can_use(sk):
                return sk

    # 没匹配到 → fallback
    if skill_name == "等待":
        return None
    return _fallback_pick(fighter, enemies)


def _fallback_pick(fighter, enemies: list) -> Optional[dict]:
    """默认技能选择：优先攻击技，否则防御"""
    live = [e for e in enemies if not e.lost]
    if not live:
        return None

    # 崩盘时优先格挡
    if fighter.broken:
        for sk in fighter.skills:
            if sk.get("type") == "defense" and fighter.can_use(sk):
                return sk

    # 否则选第一个可用的攻击技能
    for sk in fighter.skills:
        if sk.get("type") in ("defense",) or sk.get("category") == "被动":
            continue
        if fighter.can_use(sk):
            return sk

    return None
