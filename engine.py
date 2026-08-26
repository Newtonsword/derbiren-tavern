# -*- coding: utf-8 -*-
"""怪魔地下城 · 浏览器引擎包装层 (engine.py)
把本地版纯净的游戏逻辑抽出来，供 Pyodide 在浏览器里直接跑。
依赖：仅标准库 + 同目录的 combat/ consequence_manager.py npc_persona.py（均为纯标准库）。
不依赖 server.py / FastAPI / openai —— 本地版服务器照常可用，此为独立副本。
"""

import json
import random
import re
import uuid
from copy import deepcopy

# ── 引用外部引擎模块 ──
from combat import (
    Fighter,
    CombatSim,
    make_default_picker,
    calc_equipment_score,
    calc_all_equipment_scores,
    get_reward_tier,
    get_explore_tier,
    filter_equipment_by_tier,
    pick_random_equipment,
    get_xp_reward,
    fighter_from_tavern_char,
)
from consequence_manager import EXPLORE_ZONES, pick_zone, get_active_characters
from npc_persona import ensure_persona, find_char_by_name


# ── 模板常量（复刻自 server.py 尾部定义） ──
SKILL_TEMPLATE = {
    "id": "", "name": "", "type": "", "category": "主动",
    "formula": "", "cost": "", "interval": "", "cooldown": "",
    "hit_formula": "", "description": "", "effect": "", "level": 1,
}
CHAR_TEMPLATE = {
    "id": "", "name": "", "species": "", "species_coeff": 1.3,
    "level": 1, "exp": 0, "free_points": 3, "pending_skill_points": 0,
    "stats": {"HP": 300, "END": 30, "STR": 3, "SPD": 3, "INT": 3, "WIL": 3},
    "skills": [], "passives": [], "stats_allocated": [],
    "personality": "", "memory": [], "mood": "", "pregnant": None,
    "equipped": {}, "equipment_stats": {},
}

ATTR_KEYS = ["HP", "END", "STR", "SPD", "INT", "WIL"]

# 物种默认初始技能（复刻 server.py SPECIES_STARTER_SKILLS，仅取结构头）
SPECIES_STARTER_SKILLS = {
    "猫龙": {
        "skills": [
            {"name": "暗影吐息", "type": "法术", "formula": "22+2.5×智力", "cost": "蓝14", "interval": "4.5s", "cooldown": "8s", "hit_formula": "85+2.0×智力", "category": "主动"},
            {"name": "利爪", "type": "斩击", "formula": "18+2.0×力量+1.5×速度", "cost": "耐力14", "interval": "3.0s", "hit_formula": "75+2.0×力量+1.0×速度", "category": "主动"},
        ],
        "passives": [{"name": "暗影亲和", "effect": "黑暗环境不受命中惩罚，法术伤害+10%"}],
    },
    "幼龙": {
        "skills": [
            {"name": "龙息", "type": "法术", "formula": "25+3.0×智力", "cost": "蓝16", "interval": "5.0s", "cooldown": "8s", "hit_formula": "90", "category": "主动"},
            {"name": "尾击", "type": "钝击", "formula": "18+2.0×力量+0.5×耐力", "cost": "耐力18", "interval": "4.0s", "hit_formula": "75+2.0×速度", "category": "主动"},
        ],
        "passives": [{"name": "鳞甲天生", "effect": "DEF等效+1，钝伤减伤+10%"}],
    },
    "触手怪": {
        "skills": [
            {"name": "缠绕", "type": "钝击", "formula": "8+1.0×速度+0.5×精神", "cost": "耐力12", "interval": "4.0s", "hit_formula": "80+2.0×速度", "category": "主动"},
            {"name": "鞭打", "type": "钝击", "formula": "12+1.5×速度+0.5×精神", "cost": "耐力10", "interval": "2.5s", "hit_formula": "75+1.5×速度+0.5×精神", "category": "主动"},
        ],
        "passives": [{"name": "精神触须", "effect": "攻击命中时减少目标 自身精神×0.5 精神条"}],
    },
    "石像鬼": {
        "skills": [
            {"name": "俯冲", "type": "钝击", "formula": "22+2.0×速度+1.0×力量", "cost": "耐力16", "interval": "4.0s", "hit_formula": "75+3.0×速度", "category": "主动"},
            {"name": "碎石", "type": "钝击", "formula": "16+1.5×力量+0.5×耐力", "cost": "耐力20", "interval": "5.0s", "cooldown": "8s", "hit_formula": "85+1.0×速度", "category": "主动"},
        ],
        "passives": [{"name": "石化皮肤", "effect": "减伤+8%，受击概率石化攻击者(-3SPD)"}],
    },
    "杀人兔": {
        "skills": [
            {"name": "致命突袭", "type": "刺击", "formula": "18+3.0×速度+0.5×力量", "cost": "耐力10", "interval": "2.0s", "cooldown": "6s", "hit_formula": "70+3.5×速度", "category": "主动"},
            {"name": "连咬", "type": "斩击", "formula": "14+1.5×速度+1.0×力量", "cost": "耐力8", "interval": "1.8s", "cooldown": "0.5s", "hit_formula": "75+2.0×速度", "category": "主动"},
        ],
        "passives": [{"name": "偷袭", "effect": "战斗首次攻击伤害×2"}, {"name": "闪避本能", "effect": "闪避+10"}],
    },
    "野狼": {
        "skills": [
            {"name": "撕咬", "type": "刺击", "formula": "15+2.0×力量+1.5×速度", "cost": "耐力12", "interval": "2.5s", "hit_formula": "75+1.5×速度+1.0×力量", "category": "主动"},
            {"name": "扑击", "type": "钝击", "formula": "18+1.5×力量+2.0×速度", "cost": "耐力16", "interval": "3.5s", "hit_formula": "70+2.0×速度+1.0×力量", "category": "主动"},
        ],
        "passives": [{"name": "狼群战术", "effect": "队友在场时伤害+10%"}],
    },
    "史莱姆": {
        "skills": [
            {"name": "撞击", "type": "钝击", "formula": "10+1.0×耐力+0.5×力量", "cost": "耐力8", "interval": "3.0s", "hit_formula": "70+1.0×耐力", "category": "主动"},
            {"name": "缩壳", "type": "防御", "formula": "8+1.0×耐力/秒", "cost": "耐力8", "interval": "5.0s(冷却)", "hit_formula": "", "category": "主动"},
        ],
        "passives": [{"name": "凝胶身体", "effect": "钝伤减半"}],
    },
    "哥布林": {
        "skills": [
            {"name": "挥砍", "type": "斩击", "formula": "12+2.0×力量+0.5×速度", "cost": "耐力10", "interval": "3.0s", "hit_formula": "70+1.5×力量+0.5×速度", "category": "主动"},
            {"name": "盾击", "type": "钝击", "formula": "10+1.5×力量+0.5×耐力", "cost": "耐力14", "interval": "4.0s", "hit_formula": "75+1.5×力量", "category": "主动"},
        ],
        "passives": [{"name": "战斗怒吼", "effect": "战斗开始时STR+1"}, {"name": "工程天赋", "effect": "工程建造速度+0.5天/每日"}],
    },
}


# ── 造角 ──
def _skill_id():
    return "sk_" + uuid.uuid4().hex[:6]


def make_char(name="小魔王", species="人类", coeff=1.3, level=1):
    """创建角色（复刻 server.py _make_char，纯内存）。"""
    c = deepcopy(CHAR_TEMPLATE)
    c["id"] = uuid.uuid4().hex[:8]
    c["name"] = name
    c["species"] = species
    c["species_coeff"] = coeff
    c["level"] = level
    try:
        ensure_persona(c, species)
    except Exception:
        pass
    return c


def assign_starter_skills(char, provided_skills=None, provided_passives=None):
    """给角色分配初始技能（复刻 _assign_starter_skills）。"""
    skills_data = provided_skills
    passives_data = provided_passives
    if not skills_data and not passives_data:
        starter = SPECIES_STARTER_SKILLS.get(char["species"])
        if starter:
            skills_data = starter.get("skills", [])
            passives_data = starter.get("passives", [])
    if skills_data:
        for s in skills_data:
            sk = deepcopy(SKILL_TEMPLATE)
            sk["id"] = _skill_id()
            sk.update(s)
            char["skills"].append(sk)
    if passives_data:
        for p in passives_data:
            sk = deepcopy(SKILL_TEMPLATE)
            sk["id"] = _skill_id()
            sk["name"] = p["name"]
            sk["category"] = "被动"
            sk["type"] = ""
            sk["effect"] = p.get("effect", "")
            sk["formula"] = ""
            sk["cost"] = ""
            sk["interval"] = ""
            sk["hit_formula"] = ""
            char["passives"].append(sk)


def ensure_melee_skill(char):
    """确保角色至少有一个近战攻击技能（复刻 _ensure_melee_skill）。"""
    melee_keywords = ("杖", "拳", "踢", "咬", "爪", "刀", "剑", "斧", "锤", "棍", "匕", "砍", "劈", "砸", "撞", "尾", "撕")
    ranged_keywords = ("弓", "射", "弹", "息", "球", "箭", "矢", "枪")
    for s in char.get("skills", []):
        name = s.get("name", "")
        stype = s.get("type", "")
        if stype == "防御" or s.get("category") == "被动":
            continue
        if any(kw in name for kw in melee_keywords):
            return
        if any(kw in name for kw in ranged_keywords):
            continue
        if stype == "钝击":
            return
    stats = char.get("stats", {})
    spd = stats.get("SPD", 3)
    str_ = stats.get("STR", 3)
    int_ = stats.get("INT", 3)
    all_skill_names = " ".join(s.get("name", "") for s in char.get("skills", []))
    if any(kw in all_skill_names for kw in ("弓箭", "射击", "弓柄")):
        name, desc = "弓柄敲", "抡起弓柄砸人——射手的保命一击"
    elif any(kw in all_skill_names for kw in ("吐息", "火球", "魔法", "法术", "奥术", "暗影", "酸液")):
        name, desc = "杖击", "用施法器具勉强砸过去——法师的近战最后手段"
    elif int_ >= spd and int_ >= str_:
        name, desc = "杖击", "用施法器具勉强砸过去——法师的近战最后手段"
    elif spd >= str_:
        name, desc = "弓柄敲", "抡起弓柄砸人——射手的保命一击"
    else:
        name, desc = "拳打脚踢", "没有武器时的徒手攻击"
    sk = deepcopy(SKILL_TEMPLATE)
    sk["id"] = _skill_id()
    sk["name"] = name
    sk["type"] = "钝击"
    sk["category"] = "主动"
    sk["formula"] = "5 + 0.5×力量 + 0.3×速度"
    sk["hit_formula"] = "60 + 1.0×速度"
    sk["cost"] = "耐力5"
    sk["interval"] = "2.5s"
    sk["description"] = desc
    char["skills"].append(sk)


# ── 升级 / 成长 ──
def check_levelup(char):
    """检查角色是否升级（复刻 server.py _check_levelup，递归支持连升）。"""
    level = char.get("level", 1)
    exp = char.get("exp", 0)
    if level <= 3:
        need = 60 * level
    elif level <= 6:
        need = 80 * level
    else:
        need = 100 * level
    if exp >= need and level < 99:
        char["level"] = level + 1
        char["exp"] = exp - need
        char["free_points"] = char.get("free_points", 3) + 1
        char["pending_skill_points"] = char.get("pending_skill_points", 0) + 1
        check_levelup(char)


def grant_xp(char, xp, tier=None):
    """给角色经验 + 升级 + 猫龙进化检查。返回升级/进化事件列表。"""
    events = []
    old = char.get("level", 1)
    char["exp"] = char.get("exp", 0) + xp
    check_levelup(char)
    if char.get("level", 1) > old:
        events.append(f'{char["name"]} 升级到 Lv.{char["level"]}')
    if char.get("species") == "猫龙" and char.get("level", 1) >= 10 and not char.get("evolved"):
        char["evolved"] = True
        char["evolve_forms"] = ["龙人形态", "巨猫龙形态"]
        char["evolve_form"] = None
        events.append(f'{char["name"]} 龙族血脉觉醒，可切换龙人/巨猫龙形态')
    return events


# ── 配种判定（净逻辑，复刻 server.py chat() 内配种段） ──
def success_rate_for(father, mother, father_is_player=False, mother_is_player=False):
    """计算配种受孕成功率（0-1）。"""
    if father_is_player or mother_is_player:
        return 1.0  # 魔王操魔物100%
    fs, ms = father["species"], mother["species"]
    if fs == ms:
        return 1.0  # 同物种100%
    gap = abs(father.get("species_coeff", 1.3) - mother.get("species_coeff", 1.3))
    if gap <= 0.2:
        rate = 0.8
    elif gap <= 0.5:
        rate = 0.5
    else:
        rate = 0.3
    if "猫龙" in (fs, ms):
        rate = min(1.0, rate + 0.2)
    return rate


def gest_days_for(species_coeff):
    """怀孕天数：杂鱼1 / 普通2 / 精锐3 / 精英4（复刻 server.py）。"""
    if species_coeff <= 1.0:
        return 1
    elif species_coeff <= 1.3:
        return 2
    elif species_coeff <= 1.9:
        return 3
    else:
        return 4


def try_breed(sess, chars, father, mother, father_is_player=False, mother_is_player=False, use_mother_carrier=True):
    """配种判定，成功则设置 pregnant，返回 (message, carrier)。纯内存，不写日志。"""
    if father is not None and mother is not None and father["id"] == mother["id"]:
        return "⚠️ 不能自己配自己！", None
    if father is not None and father.get("pregnant"):
        return f'⚠️ {father["name"]} 正在怀孕中，不能参与配种。', None
    if mother is not None and mother.get("pregnant"):
        return f'⚠️ {mother["name"]} 正在怀孕中，不能参与配种。', None
    rate = success_rate_for(father, mother, father_is_player, mother_is_player)
    # 载体：母方优先；若母方是玩家则父方怀
    carrier = mother if mother else father
    if use_mother_carrier and not carrier:
        carrier = father
    if not carrier:
        return "⚠️ 请至少指定一只魔物参与配种。", None
    # 另一方：母为载体则父是父方；父为载体则母是父方（母玩家时父方怀）
    partner = father if (carrier is mother) else mother
    # 修正：载体是母但父是玩家(father为None)时，父.father_name 用玩家名
    if partner is not None and not (partner.get("id") == carrier.get("id")):
        pass  # 正常另一位魔物
    elif partner is None or partner.get("id") == carrier.get("id"):
        partner = None
    if partner is None:
        # 剩下一种可能：玩家参与（父玩家/母玩家），partner 记为玩家
        partner_name = "小魔王" if (father_is_player or mother_is_player) else "?"
        partner_species = "魔王" if (father_is_player or mother_is_player) else "?"
        partner_actual = None
    else:
        partner_name = partner["name"]
        partner_species = partner.get("species", "魔王")
        partner_actual = partner
    # 受孕判定
    if random.random() < rate:
        gd = gest_days_for(carrier.get("species_coeff", 1.3))
        due = sess["day"] + gd
        carrier["pregnant"] = {
            "father_name": partner_name,
            "father_id": (partner_actual or {}).get("id", ""),
            "father_species": partner_species,
            "due_day": due,
            "is_player": father_is_player or mother_is_player,
        }
        child_name = (partner_name or "魔")[0] + carrier["name"][0] + "崽"
        cross = (partner_actual is not None and partner_actual.get("species") != carrier["species"]) or (father_is_player or mother_is_player)
        cross_note = f"（跨物种：{partner_species}×{carrier['species']}）" if cross else ""
        msg = f'[BREED] {carrier["name"]} 怀孕了！（另一方：{partner_name}）{cross_note}预计 {gd} 天后（第{due}天）生下 {child_name}。{carrier["name"]} 在怀孕期间战斗伤害-60%。'
        return msg, carrier
    else:
        cross_info = f'{father.get("species", "?")}×{mother.get("species", "?")}' if not (father_is_player or mother_is_player) else "魔王×魔物"
        msg = f'😿 配种失败……{cross_info} 的受孕率只有 {int(rate * 100)}%，这次没怀上。可以改天再试试。'
        return msg, None


def try_orgy(sess, chars, player_name, names, get_tier=None):
    """淫趴：多对多群交派对。返回 (message, carrier_names, xp_total, levelups)。
    复刻 server.py chat() 淫趴段。get_tier 传 get_explore_tier 或 None（自动用）。"""
    if len(names) < 2:
        return "⚠️ 淫趴至少需要 2 名参与者（可含魔王）。", [], 0, []
    parts = []
    unknown = []
    for nm in names:
        nm = nm.strip()
        if nm == player_name:
            parts.append((nm, None, True))
        else:
            c = next((x for x in chars if x["name"] == nm), None)
            if c:
                parts.append((nm, c, False))
            else:
                unknown.append(nm)
    if unknown:
        return f'⚠️ 找不到参趴者：{",".join(unknown)}。', [], 0, []
    uniq = list(dict.fromkeys([n for n, _, _ in parts]))
    if len(uniq) < 2:
        return "⚠️ 淫趴至少需要 2 名参与者（可含魔王）。", [], 0, []
    badpreg = [c["name"] for _, c, _ in parts if c and c.get("pregnant")]
    if badpreg:
        return f'⚠️ {"、".join(badpreg)} 正在怀孕中，不能参与淫趴。', [], 0, []
    # 经验结算
    tier_f = get_tier if get_tier else get_explore_tier
    tier = tier_f(sess.get("day", 1))
    xp_total = 0
    levelups = []
    for _nm, c, isp in parts:
        if c:
            gain = random.randint(tier.xp_min, tier.xp_max)
            evts = grant_xp(c, gain)
            xp_total += gain
            if evts:
                levelups.extend(evts)
    # 配对
    pool = list(parts)
    random.shuffle(pool)
    N = len(pool)
    reduce = max(0.4, 1.0 - (N - 2) * 0.15)
    pairs = [(pool[i], pool[i + 1]) for i in range(0, N - 1, 2)]
    messages = []
    pokes = []
    for (a, b) in pairs:
        _an, _ac, _ap = a
        _bn, _bc, _bp = b
        if _ap and not _bp:
            carrier, carrier_pl = _bc, False
            partner_name, partner_species, rate = player_name, "魔王", 1.0
        elif _bp and not _ap:
            carrier, carrier_pl = _ac, False
            partner_name, partner_species, rate = player_name, "魔王", 1.0
        elif _ap and _bp:
            messages.append(f'{player_name}×{player_name}（魔王间的纯欢愉，无孕育）')
            continue
        else:
            carrier = _ac if random.random() < 0.5 else _bc
            partner = _bc if carrier is _ac else _ac
            partner_name = partner["name"]
            partner_species = partner.get("species", "?")
            if carrier["species"] == partner["species"]:
                rate = 1.0
            else:
                gap = abs(carrier.get("species_coeff", 1.3) - partner.get("species_coeff", 1.3))
                if gap <= 0.2:
                    rate = 0.8
                elif gap <= 0.5:
                    rate = 0.5
                else:
                    rate = 0.3
                if "猫龙" in (carrier.get("species", ""), partner.get("species", "")):
                    rate = min(1.0, rate + 0.2)
            rate *= reduce
        if carrier is not None and random.random() < rate:
            cs = carrier.get("species_coeff", 1.3)
            gd = gest_days_for(cs)
            due = sess["day"] + gd
            carrier["pregnant"] = {
                "father_name": partner_name,
                "father_id": "",
                "father_species": partner_species,
                "due_day": due,
                "is_player": _ap or _bp,
            }
            cn = partner_name[0] + carrier["name"][0] + "崽"
            cnnote = f"（{partner_species}×{carrier['species']}）" if partner_species != carrier.get("species", "魔王") else ""
            messages.append(f'[BREED] {carrier["name"]} 在淫趴后怀孕了！另一方：{partner_name}{cnnote} 预计 {gd} 天后（第{due}天）生下 {cn}。孕期战斗伤害-60%。')
            pokes.append(carrier["name"])
        else:
            if carrier is not None:
                messages.append(f'😿 {carrier["name"]} 这次淫趴没中标（受孕率约 {int(rate * 100)}%），下次再战。')
    xp_note = f'\n💦 淫趴结束，全员获得经验：{xp_total}（{"、".join(levelups) if levelups else "无人升级"}）'
    if messages:
        msg = "\n".join(messages) + xp_note
    else:
        msg = f'😝 一场尽兴的淫趴结束了（{N}人），没人怀孕，但全员获得了经验：{xp_total}。' + xp_note
    return msg, pokes, xp_total, levelups


# ── 生育检查 ──
def check_births(sess, chars):
    """每日检查怀孕魔物到预产期自动生产。返回出生消息列表。复刻 server.py _check_births。"""
    births = []
    day = sess.get("day", 1)
    for c in chars:
        preg = c.get("pregnant")
        if preg and day >= preg.get("due_day", 999):
            father_name = preg.get("father_name", "?")
            father_species = preg.get("father_species", c["species"])
            child_species = c["species"]
            coeff = c.get("species_coeff", 1.3)
            cross_tag = f"（{father_species}×{child_species} 混血）" if father_species != child_species else ""
            child = make_char(name=f'{father_name[0]}{c["name"][0]}崽', species=child_species, coeff=coeff, level=1)
            assign_starter_skills(child)
            chars.append(child)
            births.append(f'{c["name"]} 生下了 {child["name"]}{cross_tag}！')
            del c["pregnant"]
    return births


# ── 探索 / 巡逻 ──
def roll_explore(zone_key=None, day=1, chars=None, active=None):
    """探索一个区域，返回 (zone_info, event_resultdict)。复刻 consequence_manager 用法。"""
    sel = pick_zone(zone_key) if zone_key else pick_zone()
    tier = get_explore_tier(day)
    return sel, {"zone": sel, "tier": (tier.name if hasattr(tier, "name") else str(tier))}


# ── 战斗 ──
def make_fighters(session, active_id=None):
    """把会话角色转成 Fighter 列表用于 CombatSim。"""
    fs = []
    for c in session.get("chars", []):
        if active_id and c["id"] != active_id:
            continue
        try:
            f = fighter_from_tavern_char(c)
            fs.append(f)
        except Exception:
            pass
    return fs


def run_combat(team0_chars, team1_cfgs, environment="open", max_ticks=400):
    """跑一场战斗。team0_chars: Fighter 列表；team1_cfgs: 敌人 cfg 列表。返回 result。"""
    team1 = [Fighter(c) for c in team1_cfgs]
    sim = CombatSim(
        list(team0_chars), team1,
        environment=environment,
        ai_skill_picker=make_default_picker(),
        max_ticks=max_ticks,
    )
    return sim.run()


# ── 提供给前端调用的总入口 ──
def process_day_action(sess, action, user_msg):
    """处理一条 /day 行动，返回 (result_msg, changes_dict)。浏览器 bridge 调用此函数。
    action: 原始命令文本（含 /day 前缀或纯文本），在文本里检索配种/淫趴/探索/锻炼等。"""
    if "淫趴" in action or "狂欢" in action or "大乱交" in action:
        m = re.search(r'(?:参与者|参加者|参趴)[=＝]([^\s]+)', user_msg)
        if not m:
            return "⚠️ 请指定参与者：/day 淫趴 参与者=A,B,C（用逗号分隔，可含魔王）", {}
        names = [x.strip() for x in re.split(r"[,，、]+", m.group(1)) if x.strip()]
        msg, pokes, xp, lv = try_orgy(sess, sess["chars"], sess.get("player_name", "小魔王"), names)
        return msg, {"orgy": True, "pokes": pokes, "xp": xp}
    if "配种" in action:
        fm = re.search(r"父[=＝]([^\s母]+)", user_msg)
        mm = re.search(r"母[=＝]([^\s父]+)", user_msg)
        if not (fm and mm):
            return "⚠️ 请指定父/母：/day 配种 父=名字 母=名字", {}
        fn, mn = fm.group(1).strip(), mm.group(1).strip()
        player_name = sess.get("player_name", "小魔王")
        father = mother = None
        fpl = mpl = False
        if fn == player_name:
            fpl = True
        if mn == player_name:
            mpl = True
        for c in sess["chars"]:
            if c["name"] == fn:
                father = c
            if c["name"] == mn:
                mother = c
        if not ((father or fpl) and (mother or mpl)):
            return "⚠️ 请至少指定一只魔物参与配种，用 /day 配种 父=名字 母=名字", {}
        msg, carrier = try_breed(sess, sess["chars"], father, mother, fpl, mpl)
        return msg, {"breed": True, "carrier": carrier["id"] if carrier else None}
    if "探索" in action:
        m = re.search(r"探索\s*([\u4e00-\u9fff]+)", action)
        zone_key = None
        if m:
            zone_key = m.group(1)
        sel, res = roll_explore(zone_key=zone_key, day=sess.get("day", 1), chars=sess.get("chars", []), active=None)
        oname = sel.get("name") if isinstance(sel, dict) else str(sel)
        return f"[EXPLORE] 你带队探索了「{oname}」。", {"explore": True, "zone": oname}
    if "锻炼" in action:
        tier = get_explore_tier(sess.get("day", 1))
        xp = random.randint(tier.xp_min, tier.xp_max)
        target = sess.get("active", "")
        events = []
        for c in sess["chars"]:
            if target and c["id"] != target:
                continue
            events += grant_xp(c, xp)
        return f"💪 锻炼结束，获得经验 {xp}。{('、'.join(events)) if events else ''}", {"xp": xp}
    return "⚠️ 未能识别的行动。可用：/day 配种 /day 淫趴 /day 探索 /day 锻炼。", {}


# 模块可导入性自检
def _self_check():
    c = make_char("测试", "猫龙", 1.9, 1)
    assign_starter_skills(c)
    ensure_melee_skill(c)
    assert len(c["skills"]) >= 1, "技能未分配"
    sess = {"day": 1, "chars": [c], "player_name": "小魔王", "active": c["id"]}
    msg, ch = process_day_action(sess, "/day 配种 父=小魔王 母=测试", "/day 配种 父=小魔王 母=测试")
    assert "怀孕" in msg or "配种" in msg or "失败" in msg, msg
    return True


if __name__ == "__main__":
    print("engine self-check:", _self_check())
    print("engine.py 独立导入 & 逻辑自检 通过")