# -*- coding: utf-8 -*-
"""
NPC 独立心智模块（P0-1）
========================
derbiren-tavern 深化：让每个魔物角色拥有独立人格（personality/memory/goal/secret），
玩家 @角色名 对话时，切换成该角色的独立 system prompt（NPC agent 化），
不再让 GM 一人分饰所有角色。

用法：
    from npc_persona import build_npc_system_prompt, extract_npc_target, update_npc_memory

设计原则（参考 covel / project-lunar / gamentic）：
    - 每个 NPC 是独立 agent，不是 GM 的变声
    - NPC 有跨回合记忆（memory list），行为有连续性
    - NPC 不能越权改世界（世界权限由 engine 裁决，见 propose_change 模块）
"""

import re
import json
import random

# 性格模板池——新角色随机/按物种分配
PERSONALITY_POOL = [
    "毒舌但护短——嘴上骂骂咧咧，关键时刻第一个冲上去",
    "胆小怕事——遇到危险先躲，但被鼓励后会拼尽全力",
    "傲娇——嘴上说不要，身体很诚实，被夸奖会脸红",
    "忠犬型——无条件服从魔王，喜欢被摸头",
    "冷静理性——说话简短，行动前先分析利弊",
    "天真烂漫——对一切都好奇，容易相信别人",
    "阴沉寡言——话少，但偶尔蹦出一句毒舌吐槽",
    "热血笨蛋——不管三七二十一先冲再说",
]

# 物种→性格倾向映射（可选，不匹配就随机）
SPECIES_PERSONALITY_HINT = {
    "猫龙": "傲娇且粘人，喜欢用尾巴蹭主人",
    "史莱姆": "天真烂漫，说话软绵绵的",
    "石像鬼": "阴沉寡言，偶尔毒舌",
    "杀人兔": "外表可爱内心狂暴，反差极大",
    "魅魔": "毒舌撩人，但只对魔王温柔",
    "树精": "冷静理性，说话像老树一样慢悠悠",
    "狼妖": "忠犬型，耳朵会因情绪转动",
    "灵猫": "傲娇，喜欢被夸但绝不承认",
}

GOAL_POOL = [
    "变强，获得魔王大人的认可",
    "保护地下城的其他同伴",
    "攒够钱买一件想要的装备",
    "学会一种新的强力技能",
    "证明自己不是最弱的那个",
    "探索地下城外面的世界",
]

SECRET_POOL = [
    "其实害怕黑暗，但从不承认",
    "偷偷喜欢魔王大人，不敢说",
    "以前被冒险者抓过，留下了心理阴影",
    "不是纯血物种，是混血儿",
    "存了一笔私房钱在育成室地板下",
    "曾经偷偷放走过一只受伤的冒险者",
]


def ensure_persona(char: dict, species: str = None) -> dict:
    """确保角色有 persona 字段。没有则按物种/随机生成。"""
    if char.get("persona"):
        return char["persona"]
    sp = species or char.get("species", "")
    hint = SPECIES_PERSONALITY_HINT.get(sp)
    if hint:
        personality = hint
    else:
        personality = random.choice(PERSONALITY_POOL)
    persona = {
        "personality": personality,
        "memory": [],          # 跨回合记忆 [{"turn": n, "event": "..."}, ...]
        "goal": random.choice(GOAL_POOL),
        "secret": random.choice(SECRET_POOL),
        "mood": "平静",        # 当前心情：平静/高兴/生气/害怕/害羞...
        "relationship": "忠诚",  # 与魔王的关系：忠诚/崇拜/依赖/别扭...
    }
    char["persona"] = persona
    return persona


def extract_npc_target(text: str) -> str | None:
    """从玩家消息提取 @角色名 目标。返回角色名或 None。"""
    m = re.search(r"@([\w\u4e00-\u9fff]{1,12})", text)
    if m:
        return m.group(1).strip()
    return None


def find_char_by_name(chars: list, name: str):
    """按名称（忽略大小写/空白）查找角色。"""
    if not name:
        return None
    name_l = name.strip().lower()
    for c in chars:
        if c.get("name", "").strip().lower() == name_l:
            return c
    return None


def build_npc_system_prompt(char: dict, gm_base: str, day: int) -> str:
    """
    构建 NPC 独立 system prompt。
    玩家 @角色名 对话时，用这个替换 GM 的 system prompt（或作为附加 agent）。
    """
    persona = ensure_persona(char)
    memory_text = "\n".join(
        f"- 第{m['turn']}天: {m['event']}" for m in persona.get("memory", [])[-10:]
    ) or "- （暂无记忆）"
    skills_text = ", ".join(s["name"] for s in char.get("skills", [])) or "无"
    return f"""你是「小魔王地下城」中的角色【{char['name']}】（{char.get('species', '未知物种')} Lv.{char.get('level', 1)}）。

【你的身份】你不是 GM，你是这个世界的居民。你只扮演自己，不知道别人心里在想什么。

【性格】{persona['personality']}
【当前心情】{persona['mood']}
【与魔王的关系】{persona['relationship']}
【你当前的目标】{persona['goal']}
【你的秘密】{persona['secret']}（不到万不得已绝不提起，也不会告诉别人）

【你的记忆】
{memory_text}

【你的能力】
- 等级: {char.get('level', 1)}
- 技能: {skills_text}
- 属性: {json.dumps(char.get('stats', {}), ensure_ascii=False)}

【扮演规则】
1. 你只从自己的视角说话——不替别人做主，不替 GM 叙述世界。
2. 你说话带自己的性格特点（语气/口头禅/身体语言）。
3. 你记得自己的记忆，忘掉没经历过的事。
4. 你的秘密不会被你主动说出来——除非关系足够信任。
5. 你不知道魔王内心的想法——你只能猜测。
6. 对话长度 1-3 句，保持自然，不堆设定。
7. 绝对不能修改游戏数据（属性/技能/装备/HP）——那是魔王和系统的事。

【世界观背景】{gm_base[:500]}
当前是第{day}天。
"""


def update_npc_memory(char: dict, event: str, day: int, max_mem: int = 30):
    """往角色记忆追加一条事件（截断到 max_mem 条）。"""
    persona = ensure_persona(char)
    persona["memory"].append({"turn": day, "event": event})
    if len(persona["memory"]) > max_mem:
        persona["memory"] = persona["memory"][-max_mem:]


def update_npc_mood(char: dict, mood: str):
    """更新角色心情。"""
    persona = ensure_persona(char)
    persona["mood"] = mood


def personas_to_context(chars: list) -> str:
    """把所有角色 persona 摘要注入 GM 上下文（GM 知道每个角色的内心设定，扮演更一致）。"""
    lines = []
    for c in chars:
        p = ensure_persona(c)
        lines.append(
            f"- {c.get('name','?')}（{c.get('species','?')}）: {p['personality']} | "
            f"目标:{p['goal']} | 心情:{p['mood']}"
        )
    return "\n".join(lines) if lines else "（暂无角色）"
