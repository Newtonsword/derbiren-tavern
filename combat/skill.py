"""
技能定义与解析 —— 将 tavern 技能格式转换为战斗引擎可用格式

tavern 技能格式 (来自 skill_library.json / 角色技能):
  技能名:类型:公式:消耗:间隔
  例: 利爪:斩击:30+2.0×力量+1.5×速度:耐力22:3.5s

转换后:
  {name, type, formula, stamina_cost, mana_cost, cooldown, windup, recovery}
"""

import re

# ── 解析 tavern 技能字符串 ──
def parse_tavern_skill(raw: str) -> dict:
    """
    解析 "技能名:类型:公式:消耗:间隔" 格式
    消耗格式: "耐力22" / "蓝10" / "耐力15+蓝8"
    返回战斗引擎标准技能 dict
    """
    parts = raw.split(":")
    if len(parts) < 4:
        return None

    name = parts[0].strip()
    stype = parts[1].strip()
    formula = parts[2].strip()
    cost_part = parts[3].strip() if len(parts) > 3 else ""
    interval_str = parts[4].strip() if len(parts) > 4 else "3.0s"

    # 解析消耗
    stamina_cost = 0
    mana_cost = 0
    if cost_part:
        # "耐力22" / "蓝10" / "耐力15+蓝8"
        for token in cost_part.replace("+", " ").split():
            token = token.strip()
            if "耐力" in token or "耐" in token:
                try:
                    stamina_cost = float(re.sub(r'[^0-9.]', '', token))
                except:
                    pass
            elif "蓝" in token or "法" in token or "MP" in token:
                try:
                    mana_cost = float(re.sub(r'[^0-9.]', '', token))
                except:
                    pass

    # 解析间隔
    interval = 3.0
    try:
        interval = float(re.sub(r'[^0-9.]', '', interval_str))
    except:
        pass

    # 伤害类型映射
    type_map = {
        "斩击": "slash", "斩": "slash",
        "刺击": "pierce", "刺": "pierce",
        "钝击": "blunt", "钝": "blunt",
        "精神": "spirit", "法术": "spirit",
        "防御": "defense",
    }
    dmg_type = type_map.get(stype, "slash")

    # 前摇/后摇估算 (如果没有明确指定)
    windup = 0.3 if dmg_type != "spirit" else 0.6
    recovery = 0.5

    return {
        "name": name,
        "type": dmg_type,
        "formula": formula,
        "stamina_cost": stamina_cost,
        "mana_cost": mana_cost,
        "cooldown": interval,
        "windup": windup,
        "recovery": recovery,
    }


def parse_tavern_skills(skills_raw: str) -> list[dict]:
    """解析分号分隔的多技能字符串"""
    if not skills_raw:
        return []
    return [s for s in (parse_tavern_skill(s.strip()) for s in skills_raw.split(";")) if s]


def parse_skill_dict(skill_dict: dict) -> dict:
    """
    从 tavern 的 skill 字典转换为战斗引擎格式
    tavern skill 格式 (来自 skill_library.json):
    {
      "name": "利爪",
      "type": "斩击",
      "category": "主动",
      "formula": "30+2.0×力量+1.5×速度",
      "hit_formula": "85+2.5×速度",
      "cost": "耐力:22",
      "cooldown": "3.5s",
      "description": "..."
    }
    """
    name = skill_dict.get("name", "???")
    stype_raw = skill_dict.get("type", "斩击")
    category = skill_dict.get("category", "主动")

    # 类型映射
    type_map = {
        "斩击": "slash", "斩": "slash",
        "刺击": "pierce", "刺": "pierce",
        "钝击": "blunt", "钝": "blunt",
        "精神": "spirit", "法术": "spirit",
        "防御": "defense",
    }
    dmg_type = type_map.get(stype_raw, "slash")

    # 公式
    formula = skill_dict.get("formula", "")
    if not formula:
        formula = "30+2.0*STR+1.0*SPD"

    # 命中公式
    hit_formula = skill_dict.get("hit_formula", "")
    if not hit_formula and dmg_type == "spirit":
        hit_formula = "70+3.0*INT"
    elif not hit_formula:
        hit_formula = "85+2.5*SPD"

    # 消耗
    stamina_cost = 0
    mana_cost = 0
    cost_str = skill_dict.get("cost", "")
    if cost_str:
        for token in cost_str.replace(":", " ").replace("+", " ").split():
            token = token.strip()
            try:
                if "耐力" in token:
                    stamina_cost = float(re.sub(r'[^0-9.]', '', token))
                elif "蓝" in token or "法" in token:
                    mana_cost = float(re.sub(r'[^0-9.]', '', token))
            except:
                pass

    # 冷却
    cooldown_str = str(skill_dict.get("cooldown", skill_dict.get("interval", "3.0s")))
    try:
        cooldown = float(re.sub(r'[^0-9.]', '', cooldown_str))
    except:
        cooldown = 3.0

    # 前摇/后摇
    windup = 0.3 if dmg_type not in ("spirit", "defense") else 0.6
    recovery = 0.5

    # 特殊效果
    special = skill_dict.get("special", skill_dict.get("effect", ""))

    return {
        "name": name,
        "type": dmg_type,
        "category": category,
        "formula": formula,
        "hit_formula": hit_formula,
        "stamina_cost": stamina_cost,
        "mana_cost": mana_cost,
        "cooldown": cooldown,
        "windup": windup,
        "recovery": recovery,
        "special": special,
        "description": skill_dict.get("description", ""),
    }


def fighter_from_tavern_char(char: dict, team: int = 0, equipment_pool: list | None = None) -> dict:
    """
    将 tavern 角色数据转换为 Fighter 构造参数
    
    equipment_pool: equipment.json 的完整列表，用于查询装备属性
    """
    stats = char.get("stats", {})
    equipped = char.get("equipment", {})
    skills = list(char.get("skills", []))

    # 计算装备属性加成
    equip_bonus = {}
    equip_skills = []  # 装备技能(已解析)
    if equipment_pool:
        pool_by_id = {e["id"]: e for e in equipment_pool}
        for slot_key in ("weapon", "armor", "accessory"):
            eq_id = equipped.get(slot_key)
            if eq_id and eq_id in pool_by_id:
                eq = pool_by_id[eq_id]
                # 累加属性
                for k, v in eq.get("stats_bonus", {}).items():
                    equip_bonus[k] = equip_bonus.get(k, 0) + v
                for k, v in eq.get("secondary_bonus", {}).items():
                    equip_bonus[k] = equip_bonus.get(k, 0) + v
                # 装备技能
                eq_skill = eq.get("skill")
                if eq_skill and isinstance(eq_skill, dict):
                    parsed = parse_skill_dict(eq_skill)
                    if parsed:
                        parsed["source"] = f"装备:{eq['name']}"
                        equip_skills.append(parsed)

    # 物种系数
    species = char.get("species", "普通")
    species_coeff_map = {
        "史莱姆": 1.0, "哥布林": 1.3, "人类": 1.3,
        "野狼": 1.3, "猫龙": 2.5, "猫科龙": 2.5,
        "幼龙": 2.5, "石像鬼": 1.8, "普通": 1.3,
    }
    species_coeff = species_coeff_map.get(species, 1.3)

    # 转换技能
    combat_skills = []
    for sk in skills:
        if isinstance(sk, str):
            parsed = parse_tavern_skill(sk)
        else:
            parsed = parse_skill_dict(sk)
        if parsed:
            combat_skills.append(parsed)
    combat_skills.extend(equip_skills)

    return {
        "id": char.get("id", ""),
        "name": char.get("name", "???"),
        "level": char.get("level", 1),
        "species_coeff": species_coeff,
        "END": stats.get("END", stats.get("耐力", 4)),
        "STR": stats.get("STR", stats.get("力量", 4)),
        "SPD": stats.get("SPD", stats.get("速度", 5)),
        "DEF": stats.get("DEF", stats.get("防御", 2)),
        "INT": stats.get("INT", stats.get("智力", 1)),
        "WIL": stats.get("WIL", stats.get("精神", 4)),
        "MP":  stats.get("MP", stats.get("法力", 2)),
        "armor": stats.get("armor", 0),
        "equipment_bonus": equip_bonus,
        "current_hp": char.get("current_hp"),
        "current_stamina": char.get("current_stamina"),
        "current_mana": char.get("current_mana"),
        "current_spirit": char.get("current_spirit"),
        "current_armor": char.get("current_armor"),
        "team": team,
        "skills": combat_skills,
    }
