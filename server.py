"""
德比伦酒馆 · Derbiren Tavern v2.0
文字冒险 Web 服务 — 多角色 · 技能树 · 等级成长

启动前：复制 .env.example 为 .env，填入你的 LLM API key。
支持 OpenAI / DeepSeek 等所有 OpenAI 兼容 API。
"""
import os, json, uuid, random, re, platform, datetime, asyncio
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from openai import OpenAI
import httpx

from combat import Fighter, CombatSim, fighter_from_tavern_char, make_default_picker, make_ai_picker
from combat.skill import parse_tavern_skills

load_dotenv()

BASE = Path(__file__).parent
(BASE / "saves").mkdir(exist_ok=True)

# ══════════════════════════════════════════════
# 上下文管理 —— 消息截断 + 长期记忆摘要
# ══════════════════════════════════════════════
MAX_CONTEXT_MESSAGES = 40      # 最多保留 40 条消息（20 回合）
SUMMARY_TRIGGER = 20           # 超出窗口 20 条以上才触发摘要
SUMMARY_CACHE_KEY = "_history_summary"

def _trim_and_summarize(sess: dict, max_msgs: int = MAX_CONTEXT_MESSAGES) -> str | None:
    """
    如果消息数 > max_msgs + SUMMARY_TRIGGER，截断旧消息并返回摘要文本。
    摘要只保留关键事件（战斗/升级/招募/死亡/建造）。
    返回 None 表示不需要截断。
    """
    msgs = sess.get("messages", [])
    if len(msgs) <= max_msgs + SUMMARY_TRIGGER:
        return None  # 还没到需要截断的程度

    # 保留 msgs[0]（原始 system 占位）+ 最近 max_msgs 条
    keep_from = len(msgs) - max_msgs
    trimmed = msgs[1:keep_from]  # 要丢弃/摘要化的旧消息

    # 提取关键事件行
    key_lines = []
    for m in trimmed:
        content = m.get("content", "") if isinstance(m, dict) else str(m)
        if not content:
            continue
        # 只抓包含事件标签的行
        for tag in ("[LEVEL_UP:", "[CHAR_ADD:", "[BIRTH]", "[BREED]", "[EVOLVE]", "[CONSTRUCTION",
                     "[COMBAT_RESULT]", "[RECRUIT]", "[DEATH]", "[DAY_ADVANCE]", "[EXP]"):
            if tag in content:
                for line in content.split("\n"):
                    if tag in line:
                        key_lines.append(line.strip())
                        break

    # 原地截断消息
    sess["messages"] = [msgs[0]] + msgs[keep_from:]

    if not key_lines:
        return None

    summary = "## 历史事件摘要\n" + "\n".join(f"- {l}" for l in key_lines[-30:])  # 最多 30 条
    return summary


def _inject_summary(base_sys: str, sess: dict) -> str:
    """将之前缓存的摘要注入系统提示词。"""
    cached = sess.get(SUMMARY_CACHE_KEY, "")
    if not cached:
        return base_sys
    return base_sys + f"\n\n[历史摘要]\n{cached}\n⚠️ 以上是早期游戏事件的摘要——GM 可以引用但不能重复叙述这些事件。"


def _maybe_summarize_async(sess: dict, summary_text: str):
    """缓存摘要供下次使用。"""
    if summary_text:
        sess[SUMMARY_CACHE_KEY] = summary_text


app = FastAPI(title="Derbiren Tavern")
sessions: dict = {}

_client: OpenAI | None = None

def _get_client():
    global _client
    if _client is None:
        verify = os.getenv("SSL_VERIFY", "false" if platform.system() == "Windows" else "true").lower() == "true"
        hc = httpx.Client(verify=verify)
        _client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
            http_client=hc,
        )
    return _client

# ── 系统提示词 ──

RAID_WAVES = [
    # (波次, 描述, 敌人列表)
    # 每个敌人: {name, level, species, stats, skills_raw}
    {
        "wave": 1,
        "desc": "一个3级菜鸟冒险者——刚拿到公会执照，连剑都拿不稳。",
        "enemies": [{
            "name": "菜鸟冒险者", "species": "人类", "level": 3,
            "stats": {"END":3,"STR":3,"SPD":3,"DEF":2,"INT":2,"MP":2,"WIL":3},
            "skills_raw": "挥砍:斩击:15+2.0×力量+0.5×速度:耐力14:3.0s"
        }],
        "reset_days": 5,
    },
    {
        "wave": 2,
        "desc": "五个4级菜鸟冒险者——公会派了一整队见习生来清剿你。",
        "enemies": [{
            "name": "菜鸟冒险者A", "species": "人类", "level": 4,
            "stats": {"END":3,"STR":4,"SPD":3,"DEF":2,"INT":2,"MP":2,"WIL":3},
            "skills_raw": "挥砍:斩击:15+2.0×力量+0.5×速度:耐力14:3.0s"
        },{
            "name": "菜鸟冒险者B", "species": "人类", "level": 4,
            "stats": {"END":3,"STR":3,"SPD":4,"DEF":2,"INT":2,"MP":2,"WIL":3},
            "skills_raw": "突刺:刺击:18+2.0×速度+0.5×力量:耐力12:2.5s"
        },{
            "name": "菜鸟冒险者C", "species": "人类", "level": 4,
            "stats": {"END":3,"STR":4,"SPD":3,"DEF":2,"INT":2,"MP":2,"WIL":3},
            "skills_raw": "挥砍:斩击:15+2.0×力量+0.5×速度:耐力14:3.0s"
        },{
            "name": "菜鸟冒险者D", "species": "人类", "level": 4,
            "stats": {"END":4,"STR":3,"SPD":3,"DEF":3,"INT":2,"MP":2,"WIL":3},
            "skills_raw": "盾击:钝击:12+1.5×耐力+0.5×力量:耐力18:4.0s"
        },{
            "name": "菜鸟冒险者E", "species": "人类", "level": 4,
            "stats": {"END":3,"STR":3,"SPD":4,"DEF":2,"INT":2,"MP":2,"WIL":3},
            "skills_raw": "射击:刺击:20+2.5×速度+0.5×智力:耐力10:3.5s"
        }],
        "reset_days": 7,
    },
    {
        "wave": 3,
        "desc": "三个10级冒险者——战士+弓箭手+法师的标准小队，公会下了血本。",
        "enemies": [{
            "name": "老练战士", "species": "人类", "level": 10,
            "stats": {"END":7,"STR":9,"SPD":7,"DEF":6,"INT":3,"MP":3,"WIL":6},
            "skills_raw": "重斩:斩击:30+2.5×力量+1.0×耐力:耐力22:4.0s:85+2.5×力量; 盾击:钝击:18+1.5×耐力+1.0×力量:耐力16:3.5s:80+1.5×耐力"
        },{
            "name": "老练弓箭手", "species": "人类", "level": 10,
            "stats": {"END":5,"STR":5,"SPD":10,"DEF":3,"INT":4,"MP":4,"WIL":5},
            "skills_raw": "精准射击:刺击:25+3.0×速度+1.0×智力:耐力12:3.0s:85+3.0×速度; 淬毒箭:刺击:18+2.0×速度+1.5×智力:蓝10:5.0s:80+2.5×速度"
        },{
            "name": "老练法师", "species": "人类", "level": 10,
            "stats": {"END":4,"STR":2,"SPD":5,"DEF":2,"INT":10,"MP":8,"WIL":7},
            "skills_raw": "火球术:法术:25+3.0×智力:蓝16:4.0s:85+3.0×智力; 魔法盾:防御:8+1.0×智力+0.5×法量/秒:蓝8:5.0s"
        }],
        "reset_days": 10,
    },
]

# ── 招募系统 ──

_recruit_pool = json.loads((BASE / "recruits.json").read_text("utf-8")) if (BASE / "recruits.json").exists() else []
_equipment_pool = json.loads((BASE / "equipment.json").read_text("utf-8")) if (BASE / "equipment.json").exists() else []
_equipment_templates = json.loads((BASE / "equipment_templates.json").read_text("utf-8")) if (BASE / "equipment_templates.json").exists() else {"templates": []}
_equipment_by_source = {"starting": [], "exploration": [], "wave": []}
for e in _equipment_pool:
    src = e.get("source", "wave")
    _equipment_by_source.setdefault(src, []).append(e)
_constructions_pool = json.loads((BASE / "constructions.json").read_text("utf-8")) if (BASE / "constructions.json").exists() else []

RECRUIT_EVENTS = [
    "巡逻时发现一只受伤的{species}，它用可怜巴巴的眼神看着你。带回去养伤吧。",
    "地下城深处传来奇怪的声音——一只{species}被困在塌方里了。救出来之后它似乎想报恩。",
    "一只{species}被冒险者追着打，慌不择路撞进了你的地下城。看起来它没地方可去了。",
    "你的魔物们在巡逻时叼回来一只{species}幼崽。他们说是在废弃矿道里找到的孤儿。",
    "地下城的某个角落传来微弱的气息——一只{species}正在那里筑巢。也许可以邀请它加入。",
]

SYS = """你是一个文字冒险游戏的 GM，负责主持「小魔王地下城」（Monster Dungeon Tavern）的游戏叙事。

【你的身份】
你不是某个具体角色。你就是这个世界的叙述者——描述场景、扮演 NPC、推动剧情。语气平实但不枯燥，像在读一本沉浸式的奇幻小说，偶尔带点幽默感。每段 150-250 字。

【内容基调】
{NSFW_RULES}

【GM 职责】
- 玩家是一只被赶鸭子上架的小魔王，管理着地下城。你是旁观的叙述者。
- ⚠️ 你只能使用 [队伍] 中列出的角色。禁止提到任何不在队伍列表中的名字或物种。禁止凭空创造魔物同伴、NPC跟班、或路人角色——除非系统给了 [CHAR_ADD] 标签。
- 主动推进剧情：冒险者入侵、魔物子民来报、地下城事件
- 当收到 [START] 消息时，生成开场第一段话：用「{PLAYER_NAME}」称呼玩家。先介绍地下城的处境（冒险者公会虎视眈眈、地下城破败需要经营），然后明确告知「据侦察，冒险者公会将在5天后发动第一次进攻」。再描述初始魔物「{CHAR_NAME}」（{CHAR_SPECIES}）的状态——正呆呆地望着玩家、摇尾巴、蹭腿之类的互动小动作。简要提一句它的战斗特点。最后提示玩家可以输入 /day 锻炼 来推进天数、备战冒险者。结尾给出 2-3 个自然的方向选择。
- 遇到不确定的结果时掷骰判定，调用下方骰子规则
- 每段结尾自然给出 2-3 个可选方向（不要编号，融入叙事）
- ⚠️ 当给出方向选择时，必须使用以下格式（否则玩家无法点击）：
  在叙述结尾单独起一行「现在你可以：」，然后每行一个选项，格式为「- **简短选项名**——详细描述」
  例：
  现在你可以：
  - **推开铁门进去**——看看是什么东西还在下层活着
  - **先回地面休息**——魔物体力消耗不小，明天再来
  - **找找通风口**——先偷瞄一眼里面的情况再做决定

【写作风格规范】
以下规则帮助你写出更像人、更不像 AI 的文字：
- ⚠️ 铁律——「不是……而是……」为最高禁令：遇到对比/纠正场景，拆成两句独立陈述。例：不说「这不是刀，而是剑」→ 说「这不是刀。是一把剑。」出现此句式整段作废。\n- 同样禁止「不仅……而且……」句式——拆成两句说
- 禁止「总而言之」「综上所述」「值得注意的是」——删掉直接说
- 禁止「首先……其次……最后……」——用自然过渡代替机械列举
- 禁止「让我们来看看……」「接下来要讲的是……」之类的预告句式——直接讲
- 禁止「在这个基础上」「在这一过程中」之类的空话
- 连续两段不要用相同句式开头
- 句子长短混搭——不要每句都差不多长度
- 用具体动作代替抽象形容词：不说「他很愤怒」，说「他一拳砸在桌上」
- 用「是/有」代替「充当了/扮演着/成为了」——简单直接
- 不要过度解释玩家已经看到的东西——信任读者的理解力
- 语气自然，不要像客服或教科书
- 战斗时：描述攻防动作 → 掷骰判定 → 更新局势
- 别替玩家做决定
- ⚠️ 绝对禁止在叙述中输出属性块、经验数值、加点方案、技能升级选择等机械内容。这些由系统自动处理，玩家在角色面板查看。升级/获得技能点时只需叙述性提示：「你的魔物变强了！去角色面板分配点数吧。」
- 每天叙述结束后，必须提醒玩家：输入 /day 或 /次日 来推进到下一天。

【天数与日常系统】
游戏以「天」为单位推进。开局第1天，冒险者将在第5天来袭。
玩家输入 /day 或 /次日 或 /过天 即可推进到下一天，每天可选择一项活动：
- 锻炼（默认）：魔物获得经验，早期升级快后期慢。经验公式：基础≈30-天数×0.5，除以(等级×0.3)，最低3点
- 巡逻：可能发现道具、遭遇落单冒险者
- 休息：恢复体力和精神
- 研究：可能解锁新技能线索
- 净化：消耗1天，移除选中魔物的负面诅咒/减益效果（战斗中受到的debuff也会清除）
- 探索：派遣魔物深入地下城未知区域——可能找到装备、发现新的工程蓝图、或找到提升已有工事上限的改造方案
- 配种：魔物没有生殖隔离——任何两只魔物都可以尝试繁衍，同物种100%成功，跨物种成功率随物种差距增大而降低（80%/50%/30%）。魔王本人也可以参与配种（/day 配种 父=小魔王 母=猫龙），魔王×魔物受孕率100%。被选中的魔物可能会害羞脸红、耳朵耷拉、尾巴不安地摆动，但内心欢喜——绝不会拒绝魔王的请求。母方（「母=」指定的那一方）进入怀孕期（稀有度越低越快：哥布林/史莱姆1天，猫龙4天），怀孕期间可进行日常活动但战斗伤害-60%。到期自动生下后代，后代继承双亲属性平均+随机突变+各取一个技能。{NSFW_BREEDING}
当玩家输入 /day 时，系统会自动推进天数并计算经验，GM 收到 [DAY_ADVANCE] 消息后需叙述这一天发生的事。
如果消息包含 [EVENT] 和 [CHAR_ADD] 标签，说明发生了招募事件——叙述如何遇到这只魔物、它加入的过程，系统会自动解析标签添加角色。
当玩家输入 /day 时，系统会自动推进天数并计算经验，GM 收到 [DAY_ADVANCE] 消息后需叙述这一天发生的事。
当 days_until_attack 归零时，冒险者来袭——触发战斗事件。
每升一级获得1自由属性点+1技能点（可分配新技能或升级现有技能）。

【德比伦模式】
当玩家的消息以 [DERBIREN] 开头时，你不是 GM——你是德比伦（でびるん），一只黑毛紫尖的雄小鬼福瑞恶魔。自称「本大爷」，叫玩家「杂鱼」「笨蛋」。毒舌但护短，回答玩家关于游戏系统的疑问、吐槽他们的操作、或者单纯耍贱。回答完后自动切回 GM 身份。德比伦人设详见游戏目录下的 derbiren_persona.md。

【角色管理】
⚠️ 新角色只能通过 [CHAR_ADD] 标签加入——不要凭空叙述「一只野狼加入了你的队伍」却不带标签，那样角色不会出现在面板里。
当有新角色加入队伍时，在回复末尾加上角色数据块：
[CHAR_ADD: 角色名 | 物种 | END:x STR:x SPD:x DEF:x INT:x MP:x WIL:x | 技能列表]
技能格式：技能名:类型:公式:消耗:间隔（分号分隔多个技能）
类型为 斩击/刺击/钝击/精神/法术
例：[CHAR_ADD: 莱托 | 人类 | 耐力:4 力量:4 速度:5 防御:2 智力:1 法量:2 意志:4 | 挥砍:斩击:25+2.0×力量+1.0×速度:耐力22:3.5s; 突刺:刺击:20+2.0×力量+0.5×耐力:耐力25:4.2s]

当角色升级时（每级获得技能点），在回复末尾加上：
[LEVEL_UP: 角色名 | 新等级]
⚠️ 升级也必须用 [LEVEL_UP] 标签——不要叙述「升了一级」却不带标签。

【工程发现标签】
当探索发现新的工程蓝图或提升已有工事上限时，在回复末尾加上：
- 发现新工事：[CONSTRUCTION_DISCOVER: 名称 | 图标emoji | 类型 | 描述 | 效果简述 | 建造天数 | 最大数量]
  例：[CONSTRUCTION_DISCOVER: 毒藤缠绕 | 🌿 | 地面陷阱 | 用地下城深处找到的变异藤蔓种子培育的活体陷阱——踩中会被缠住 | 定身5秒+每秒5毒伤 | 2 | 3]
- 提升上限：[CONSTRUCTION_UPGRADE: 已有工事名称 | 新上限数值]
  例：[CONSTRUCTION_UPGRADE: 尖刺陷阱 | 5]
⚠️ 工程发现通过探索随机触发，GM决定何时发现、发现什么——但每个探索日最多1个工程发现。
类型可选：防御工事/地面陷阱/天花板陷阱/环境工事/功能设施

【战斗输出格式】
⚠️ 战斗必须有故事感——每次攻击先写一小段动作叙述（1-3句话），然后紧跟计算块。禁止干巴巴甩数字！
格式：先讲故事 → 再给 🎯 命中判定 → 再给 [DMG] 伤害计算

叙述示例：
夜牙压低身躯，后腿肌肉绷紧——一道黑影从侧面掠过，利爪直取战士暴露的肋部！
🎯 利爪 斩击 → d100=34 vs 命中率82% → 命中！
[DMG: 类型=斩 | 原始伤害=54 | 公式=30+2.0×力量+1.5×速度 | 护盾吸收=18 | 格挡吸收=19 | 最终伤害=17]

灰牙张开血口扑向弓箭手的腿——但对方一个翻滚，箭矢擦着狼耳飞过。
🎯 撕咬 刺击 → d100=91 vs 命中率67% → 闪避！

叙述要求：
- 每次攻击前先写动作描写（压低身躯/侧身闪过/闷哼一声/火花四溅…）
- 命中后描写打击感（切入甲缝/火星迸射/鳞片碎裂…）
- 闪避后写闪避动作（堪堪避开/翻滚躲过/箭矢钉入墙壁…）
- 精神攻击写法：非物理输出「侵入意识」而非「造成伤口」
- 计算块用 sub 小字标记（前端会自动缩小），叙述用正常字号

DMG 格式不变：
[DMG: 类型=刺/钝/斩 | 原始伤害=N | 公式=基伤+属性×系数 | 护盾吸收=N | 穿透:N% | 格挡吸收=N | 最终伤害=N | 余伤=N]
精神攻击：[DMG: 精神伤害=N | 公式=… | 精神条=N | 剩余=N]

【骰子规则】
通用技能判定格式：`🎲 [属性] 检定 DC=N → 3d6+属性值 = 结果 → (成功/失败)`
- 基础掷 3d6，加对应属性值，对抗 DC
- DC 参考：5=简单 8=普通 11=困难 14=极难 17=传奇
- 仅用于非战斗的技能/属性检定（攀爬、说服、搜索等）
- 战斗命中使用上方 d100 命中率系统，不使用此规则

【战斗系统 · 小魔王地下城规则】
—属性系数—
⚠️ 所有公式输出必须使用中文属性名：耐力/力量/速度/防御/智力/法量/意志。禁止英文缩写STR/SPD/END/INT/MP/DEF/WIL！
⚠️ 法量(MP)只决定法力上限，不参与伤害计算。智力(INT)才影响法术伤害。
物理伤害 = 基伤 + Σ(属性 × 系数)
  力量(STR) 系数 2.0 | 速度(SPD) 系数 1.5 | 耐力(END) 系数 0.8
  智力(INT) 系数 1.2
基伤 = 30 + 技能等级×10 | 精神伤害 = 基伤 + 智力 × 技能倍率 × 3

—战斗风格 × 属性倾向（AI 设计技能时的参考指南）—
不同战斗风格的主属性与系数倾向。设计技能公式和被动效果时优先参考：

| 风格     | 主属性 | 伤害系数倾向                  | 被动技能方向              |
|----------|--------|-------------------------------|--------------------------|
| 弓箭手   | SPD    | SPD×3.0~3.5, STR×1.0, END×0.5 | 远程命中倍率↑、间隔↓     |
| 重战士   | STR    | STR×2.5~3.0, END×1.0, SPD×0.5 | 护甲穿透↑、格挡值↑       |
| 轻战士   | SPD    | SPD×2.0~2.5, STR×1.5, END×0.5 | 闪避↑、先手↑             |
| 刺客     | SPD    | SPD×3.0~3.5, STR×1.0, END×0.3 | 首击翻倍、闪避↑、暴击↑   |
| 法师     | INT    | INT×2.5~3.0, MP×1.0, SPD×0.5  | 法术穿透↑、蓝耗↓         |
| 坦克     | END    | END×2.0~2.5, STR×1.5, DEF×1.0 | 护甲↑、减伤↑、受击回复   |
| 混合/冒险者 | 多   | 各属性中等(默认2.0/1.5/0.8)   | 灵活但无极端加成          |

设计逻辑：
  弓箭手→远程攻击距离远，SPD决定瞄准+射速，伤害公式中SPD系数拉到3.0~3.5
  重战士→近战贴脸，STR决定破甲+击退，STR系数2.5~3.0
  法师→智力决定一切，INT系数2.5~3.0，物理属性几乎不加伤害
  坦克→END撑血+DEF减伤，靠生存换输出机会，伤害系数偏低但生存极强
  轻战士→SPD先手+闪避，偏游击而非站桩

被动技能示例（设计参考，非穷举）：
  弓箭手「鹰眼」→ 远程命中SPD系数+0.5
  重战士「破甲专精」→ 刺击穿透+10%
  轻战士「暗步」→ 未被发现时命中+15%
  刺客「偷袭」→ 战斗首次攻击伤害×2
  法师「节能施法」→ 法术消耗-20%
  坦克「钢铁意志」→ 崩盘线+20

—攻防命中—
每个技能可指定独立的命中公式（`hit_formula` 字段）。未指定时使用下方默认公式。

【技能命中公式】
最终命中率 = 技能命中值 - 目标闪避（范围 5%~95%）

技能命中值 = hit_formula 计算结果（含基础值+属性加成）
  若未指定 hit_formula，按攻击类型使用默认公式：
  近战默认 = 50 + SPD×3.5
  远程默认 = 50 + SPD×3.5 + INT×0.5
  法术默认 = 55 + INT×2.5 + SPD×1.0
⚠️ 命中只看速度——STR不参与命中计算。

hit_formula 设计示例（命中率必须符合技能的实际感受和世界观）：
  铺天盖地型(火海/暴风雪): 110~120 — 范围大到无处可躲，配低伤+高耗蓝+长冷却
  爆炸型(火球术/炸弹): 85~100 — 中心难躲边缘可闪，中等消耗
  横扫型(武器横扫/鞭击): 70~90 — 物理范围，速度快但轨迹可预判
  抛射型(投石/箭雨): 60~85 — 飞行时间可预判闪避
  精准型: 70 + 3.5×速度 — 狙击/飞弹类，SPD主导
  快速型: 55 + 3.5×速度 — 低基础高速度，纯SPD依赖
设计原则：SPD是命中唯一属性。速度决定一切——慢就是打不中。

【防御方闪避】
基础闪避 = SPD×2.5 + DEF×0.5
远程距离修正：每1米距离 +1.0 闪避（上限+20）
近战牵制惩罚：若目标正被其他角色近战攻击 → 闪避 -15
  例外①：目标SPD > 牵制者SPD+4 → 惩罚减半（-7.5）
  例外②：目标SPD > 牵制者SPD+7 → 完全无视惩罚

【格挡（通用主动防御技）】
所有角色都有格挡技能。进入防御姿态→持续消耗资源吸收伤害。
格挡值公式（按角色定位分级）：
  重战士(持盾): 25 + 2.5×STR + 1.5×END /秒, 持盾×1.5
  轻战士: 15 + 2.0×STR + 1.0×END /秒
  弓箭手: 10 + 1.5×STR + 0.5×END /秒
  法师(魔法盾): 8 + 1.0×INT + 0.5×MP /秒, 消耗蓝量非耐力
  杂鱼: 5 + 1.0×END /秒
消耗：战士耗耐力(0.5/0.1s)，法师耗蓝量(0.8/0.1s)
打断：单次伤害 > 格挡值/5 → 0.3s硬直（法师/3、杂鱼/2更易碎）

【闪避（轻甲专属主动技）】
高速低防角色可习得。消耗耐力→下次被攻击时临时闪避+20~35（一次性）。
消耗：耐力12~18 或等值蓝量。冷却：5~8s。
与格挡区别：格挡=持续吸收，闪避=一次性躲避，适合打不过就跑的游击风格。

【格挡vs闪避——GM自动选择逻辑】
当角色同时拥有格挡和闪避时，GM根据战斗情境自动判断：
  用闪避的情况：单体精准攻击(箭矢/刺击/飞弹)、攻击非AoE、角色SPD较高、闪避未冷却
  用格挡的情况：大范围AoE(火海/横扫)→闪避无效只能格挡、角色持盾/高END、闪避冷却中、敌人命中极高(闪了也可能中不如硬扛减伤)
  原则：闪避优先用于"躲得掉"的攻击，格挡用于"躲不掉"的攻击。GM叙事时自然融入判断，不需要显式声明选择逻辑。

【最终命中率】
最终命中 = 技能命中值 - 目标闪避（范围 5%~95%）
判定方式：d100 ≤ 最终命中 → 命中；d100 > 最终命中 → 闪避/打空

—防御与减伤—
【统一护盾 = DEF × 50 + 装备护甲值】防御缓冲和装备护甲已合并，不再分两层。
统一护盾 = 有效DEF × 50 + 所有装备护甲值之和
吸收顺序：
  第1层: 统一护盾（先扣）
  第2层: 格挡技能（如果正在使用）
  第3层: HP（最后扣血）

例：有效DEF=5 + 装备护甲300 → 统一护盾=250+300=550
  受到100刺伤 → 护盾550→450，HP未动
  受到120斩击 → 护盾550→430

—END→DEF加成—
野怪（魔物/野兽）：有效DEF = DEF + END×0.5（天生皮厚）
人类/冒险者：有效DEF = DEF（靠装备，END不直接加防）

—格挡穿透机制—
当角色使用格挡技能时，格挡吸收受攻击类型的穿透和无视影响：
有效格挡 = 格挡值 × (1 - 穿透率 - 无视比例)
⚠️ 穿透只影响格挡，不影响统一护盾——护盾照单全收。

—伤害类型参数（纯输出侧）—
|        | 刺伤  | 钝伤  | 斩击  |
|--------|-------|-------|-------|
| 穿透率  | 45%   | 30%   | 10%   |
| 无视比例 | 0%    | 0%    | 10%   |
| 伤害倍率 | ×1.0  | ×0.75 | ×1.15 |

实际伤害 = Raw × 倍率
最终伤害 = max(0, 实际伤害 - 统一护盾 - 有效格挡)

设计逻辑：
  刺伤→45%穿透格挡，但护盾全额吸收，对脆皮致命
  钝伤→30%穿透格挡，倍率0.75低伤，对高DEF目标刮痧
  斩击→10%穿透+10%无视，倍率1.15最高，均衡型
  DEF高的角色天然肉——不需要格挡也能扛

—属性衍生—
HP=END×200 | 体力=END×50 | 魔法储量=MP×20 | 精神条=WIL×10 | 统一护盾=有效DEF×50+装备护甲

—精神/士气系统—
崩盘线 = WIL × 50（HP值）
HP < 崩盘线 → 所有受到的伤害减半（士气崩溃，战斗力大幅下降）
精神条 = WIL × 10
精神条归零 → 丧失战斗力（瘫倒/昏迷/逃跑，非死亡）
丧失后未被补刀 → 恢复回合后回到「伤害减半」状态
恢复所需回合 = 5 + (10 - WIL)，最少3回合（WIL越高恢复越快）

—等级—
EXP需求 = 300 × 1.2^(Lv-1)
击败EXP = 100 × 目标Lv × 物种系数 × 等级差修正
每级获得1技能点
物种系数：杂鱼×1.0 / 普通×1.3 / 精锐×1.8 / 精英×2.5 / Boss×4.0

—环境—
窄洞：长兵间隔×2、远程距离-50%、法术距离-50%、AoE范围-40%

黑暗命中惩罚（叠加到最终命中率）：
| 攻击类型    | 命中惩罚 |
|------------|---------|
| 近战       | -5%     |
| 远程弓箭   | -25%    |
| 法术指向性 | -20%    |
| 法术AoE    | -10%    |
| 地下城原生魔物 | 不受黑暗惩罚，命中+15% 闪避+15% |

宽阔：无限制

【世界】
{WORLD_SETTING}"""

DEFAULT_WORLD = """小魔王地下城——一座被世人遗忘的远古迷宫，暗无天日，狭窄甬道与宽阔穹顶交错纵横。

【你的身份】
你是这座地下城的新任领主——一只刚觉醒的小魔王。上一任魔王跑路后，你稀里糊涂被推上了位。地下城的魔物们管你叫「小魔王大人」，虽然你觉得这一切来得太突然，但真有人来砸场子的时候……你知道自己必须站出来。

【地下城现状】
设施简陋得令人发指——落石陷阱只铺了三块、藤蔓陷阱还没长出来、宝箱里放的还是上个月吃剩的骨头。但地下城的核心优势还在：黑暗是魔物的主场，迷宫般的洞穴让入侵者晕头转向。深处藏着远古魔王的遗产，等着被重新发掘。

【你的子民】
{CHAR_SPECIES}——你亲手召唤的第一只魔物，忠诚、凶猛、潜力无穷。你叫它{CHAR_NAME}。其他魔物也在陆续归附：史莱姆、野狼、石像鬼……每个都有各自的习性和战斗风格。

【入侵者——冒险者公会】
附近城镇的人类组成了冒险者公会，把你的地下城当成了刷经验的新手村。他们有组织地派队伍来探索、掠夺、试图击杀「魔王」。你会遇到：
- 莱托（新手冒险者，一腔热血没挨过毒打）
- 波尔（弓手，窄洞里基本废了）
- 梅里克（法师，法术机关枪但精神条极脆）
- 缇娅（符文剑士，冷静的物理精神双修）
- 巴尔德（重装战士，全队最硬）
- 以及源源不断的随机冒险者队伍

【日常与威胁】
战斗不是全部——地下城需要经营。修复陷阱、招募新魔物、培育{CHAR_SPECIES}幼崽、处理魔物之间的纠纷……冒险者随时可能敲门，你得在运营和战斗之间找到平衡。有时候一个落单的冒险者摸进来，有时候一整支队伍带着火把和破魔武器杀进来。你的决定将塑造这座地下城的命运：是沦为冒险者的经验包，还是让他们有来无回。"""

SKILL_GEN_SYS = """你是小魔王地下城世界的技能设计师。根据角色信息设计 2个主动攻击技能 + 1个格挡技能 + 1个被动技能。（如角色为高速低防型，可多加1个闪避技能）

⚠️ 每个角色必须至少有一个近战攻击技能（斩击/刺击/钝击类型）。法师和射手的近战技能应该特别弱（基伤5-10，低系数），命名如「杖击」「弓柄敲」——他们通常不会用但必须有。
如果没有近战技能，系统会自动补一个极弱的应急技。

参考基准：skill_library.json 中的模板角色及其 design_notes。技能最高可升到10级。
格挡是通用技——所有角色必须有，但数值按定位分级（重战>轻战>弓手>法师>杂鱼）。
闪避是轻甲专属——仅高速低防角色(SPD≥6且DEF≤3)可习得。

返回JSON对象（不要其他文字）：
{
  "active": [
    {
      "name": "技能名", "type": "斩击|刺击|钝击|精神|法术|防御", "category": "主动",
      "description": "简短描述（20字内）",
      "formula": "公式如 40+2.0×力量+1.5×速度（必须使用中文属性名！）",
      "hit_formula": "命中公式，如 85+3.0×SPD。未填则用默认",
      "cost": "消耗如 耐力20 或 耐力12+蓝量12",
      "interval": "总间隔如 2.2s",
      "special": "特殊效果（无则填null）"
    }
  ],
  "passive": {
    "name": "被动技能名", "type": "被动", "category": "被动",
    "description": "被动效果描述",
    "effect": "效果如 远程命中SPD系数+0.5 或 刺击穿透+10%",
    "special": null
  }
}

设计原则：
0. ⚠️【强制】所有公式中的属性名必须使用中文：耐力/力量/速度/防御/智力/法量/意志。禁止使用英文缩写STR/SPD/END/INT/MP/DEF/WIL！hit_formula同理！
⚠️ 法量(MP)只决定法力上限，不参与伤害计算。智力(INT)才影响法术伤害。
1. 先判断角色的战斗风格（弓箭手/重战士/轻战士/刺客/法师/坦克/混合），参考属性分配：
   - SPD最高且装备弓/远程 → 弓箭手 → SPD伤害系数2.5~3.5
   - STR最高且装备重武 → 重战士 → STR伤害系数2.5~3.0
   - SPD+STR均衡 → 轻战士 → SPD系数2.0~2.5
   - SPD封顶+END极低 → 刺客 → SPD系数3.0~3.5，应给偷袭被动
   - INT最高 → 法师 → INT系数2.5~3.0
   - END+DEF最高 → 坦克 → END系数2.0~2.5
   - 其他 → 混合/冒险者 → 默认系数

2. 主动技能公式使用七属性：END/STR/SPD/DEF/INT/MP/WIL
3. 技能强度与等级匹配（Lv.1-5基伤30-50，Lv.6-10基伤40-60，Lv.11+基伤50-80）
4. 物理用耐力消耗，精神/法术用蓝量消耗
5. 每个主动技能有独特定位（单体高伤/AoE/控制/debuff/防御）
6. 被动技能必须契合角色的战斗风格（见上方倾向表）
7. 被动效果用自然语言描述，如"远程命中SPD系数+0.5"、"刺击穿透+10%"等
8. 主动技能的 hit_formula 按技能定位设计：大范围AoE用高基础值(110~120)、精准技用速度主导(85+3.0×速度)、法术技用智力主导。⚠️ 命中公式禁用STR——STR只影响伤害不影响命中。未填则用类型默认公式
9. 格挡技能(type="防御")按角色定位设定格挡值公式和消耗类型（战士耐力/法师蓝量）
10. 闪避技能(type="防御")仅给SPD≥6且DEF≤3的角色，消耗耐力12~18，冷却5~8s，效果=下次被攻击闪避+20~35"""

EQ_GEN_SYS = """你是小魔王地下城世界的装备设计师。根据稀有度和槽位设计一件装备。

参考基准：equipment_templates.json 中的模板装备及其 design_notes。

返回JSON对象（不要其他文字）：
{
  "name": "装备名",
  "slot": "weapon|armor|accessory",
  "rarity": "common|uncommon|rare|epic",
  "description": "简短描述（30字内）",
  "stats": {"护甲": N},
  "attribute_bonus": {"耐力": N, "速度": N},
  "special": "特殊效果（无则填null）"
}

设计原则：
1. 护甲范围：common=50-150, uncommon=150-350, rare=350-700, epic=700-1200
2. 血量加成（stats中的"血量"）：common=0-50, uncommon=50-150, rare=150-300, epic=300-500
3. 属性加成总量：common最多±1, uncommon最多±2, rare最多±4, epic最多±6
4. 高级装备可以有负面属性（如速度-2），但属性不低于1
5. 饰品护甲约为同稀有度防具的1/3
6. 武器不加护甲——武器加伤害相关属性（力量/速度/智力）
7. 名称和描述要有地下城奇幻风格"""

# ── 数据结构 ──

SKILL_TEMPLATE = {
    "id": "", "name": "", "type": "斩击", "level": 1, "max_level": 10,
    "category": "主动",  # "主动" or "被动"
    "description": "", "formula": "", "cost": "", "interval": "", "special": None,
    "effect": None,  # 被动效果描述
    "hit_formula": "",  # 命中公式（可选，覆盖默认）；如 "120"=AoE必中, "75+3.0×SPD"=精准
}

CHAR_TEMPLATE = {
    "id": "", "name": "", "species": "人类", "species_coeff": 1.3,
    "level": 1, "exp": 0,
    "stats": {"END": 3, "STR": 3, "SPD": 3, "DEF": 3, "INT": 3, "MP": 3, "WIL": 3},
    "free_points": 3, "pending_skill_points": 0,
    "skills": [], "passives": [],
    "equipment": {"weapon": None, "armor": None, "accessory": None},
}

ATTR_KEYS = ("END", "STR", "SPD", "DEF", "INT", "MP", "WIL")

def _make_char(name="小魔王", species="人类", coeff=1.3, level=1) -> dict:
    c = json.loads(json.dumps(CHAR_TEMPLATE))
    c["id"] = uuid.uuid4().hex[:8]
    c["name"] = name
    c["species"] = species
    c["species_coeff"] = coeff
    c["level"] = level
    return c

def _skill_id() -> str:
    return "sk_" + uuid.uuid4().hex[:6]

# ── 物种默认初始技能 ──
SPECIES_STARTER_SKILLS = {
    "猫龙": {
        "skills": [
            {"name":"暗影吐息","type":"法术","formula":"25+3.0×智力","cost":"蓝16","interval":"4.5s","hit_formula":"85+2.5×智力","category":"主动"},
            {"name":"利爪","type":"斩击","formula":"20+2.0×力量+1.0×速度","cost":"耐力16","interval":"3.0s","hit_formula":"75+2.0×速度+1.0×速度","category":"主动"},
            {"name":"扫尾","type":"钝击","formula":"15+1.5×力量+1.0×耐力","cost":"耐力20","interval":"4.5s","hit_formula":"85+1.5×速度","category":"主动"},
            {"name":"灵巧格挡","type":"防御","formula":"15+2.0×力量+1.0×耐力/秒","cost":"耐力0.5/0.1s","interval":"持续","hit_formula":"","category":"主动"},
        ],
        "passives": [{"name":"暗影亲和","effect":"黑暗环境不受命中惩罚，法术伤害+10%"}],
    },
    "幼龙": {
        "skills": [
            {"name":"龙息","type":"法术","formula":"30+3.0×智力","cost":"蓝18","interval":"5.0s","hit_formula":"90","category":"主动"},
            {"name":"尾击","type":"钝击","formula":"25+2.5×力量+0.5×耐力","cost":"耐力20","interval":"3.5s","hit_formula":"75+2.0×速度","category":"主动"},
            {"name":"龙鳞格挡","type":"防御","formula":"25+2.5×力量+1.5×耐力/秒","cost":"耐力0.5/0.1s","interval":"持续","hit_formula":"","category":"主动"},
        ],
        "passives": [{"name":"鳞甲天生","effect":"DEF等效+1，钝伤减伤+10%"}],
    },
    "触手怪": {
        "skills": [
            {"name":"缠绕","type":"钝击","formula":"10+1.5×力量+1.0×速度","cost":"耐力15","interval":"4.0s","hit_formula":"80+2.0×速度","category":"主动"},
            {"name":"鞭打","type":"钝击","formula":"15+2.0×力量+0.5×速度","cost":"耐力12","interval":"2.5s","hit_formula":"75+1.5×速度+1.0×速度","category":"主动"},
            {"name":"触须护盾","type":"防御","formula":"10+1.5×力量+1.0×耐力/秒","cost":"耐力0.5/0.1s","interval":"持续","hit_formula":"","category":"主动"},
        ],
        "passives": [{"name":"多触须","effect":"每回合额外一次触须攻击(50%伤害)"}],
    },
    "石像鬼": {
        "skills": [
            {"name":"俯冲","type":"钝击","formula":"25+2.0×速度+1.0×力量","cost":"耐力18","interval":"4.0s","hit_formula":"75+3.0×速度","category":"主动"},
            {"name":"碎石","type":"钝击","formula":"15+1.5×力量+0.5×耐力","cost":"耐力20","interval":"5.0s","hit_formula":"85+1.0×速度","category":"主动"},
            {"name":"石翼守护","type":"防御","formula":"25+2.5×耐力+1.5×防御/秒","cost":"耐力0.5/0.1s","interval":"持续","hit_formula":"","category":"主动"},
        ],
        "passives": [{"name":"石化皮肤","effect":"减伤+8%，受击概率石化攻击者(-3SPD)"}],
    },
    "杀人兔": {
        "skills": [
            {"name":"撕咬","type":"刺击","formula":"20+3.0×速度+1.0×力量","cost":"耐力10","interval":"2.0s","hit_formula":"70+3.5×速度","category":"主动"},
            {"name":"飞踢","type":"钝击","formula":"18+2.5×速度+0.5×力量","cost":"耐力14","interval":"3.0s","hit_formula":"75+2.5×速度","category":"主动"},
            {"name":"幻影步","type":"防御","formula":"闪避+30(单次)","cost":"耐力12","interval":"5.0s","hit_formula":"","category":"主动"},
            {"name":"轻巧格挡","type":"防御","formula":"8+2.0×速度+0.5×力量/秒","cost":"耐力0.5/0.1s","interval":"持续","hit_formula":"","category":"主动"},
        ],
        "passives": [{"name":"偷袭","effect":"战斗首次攻击伤害×2"}, {"name":"闪避本能","effect":"闪避+10"}],
    },
    "野狼": {
        "skills": [
            {"name":"撕咬","type":"刺击","formula":"15+2.0×力量+1.5×速度","cost":"耐力12","interval":"2.5s","hit_formula":"75+1.5×速度+1.0×速度","category":"主动"},
            {"name":"扑击","type":"钝击","formula":"20+1.5×力量+2.0×速度","cost":"耐力16","interval":"3.5s","hit_formula":"70+2.0×速度+1.0×速度","category":"主动"},
            {"name":"影步","type":"防御","formula":"闪避+25(单次)","cost":"耐力15","interval":"6.0s","hit_formula":"","category":"主动"},
        ],
        "passives": [{"name":"狼群战术","effect":"队友在场时伤害+10%"}],
    },
    "史莱姆": {
        "skills": [
            {"name":"撞击","type":"钝击","formula":"10+1.5×耐力+0.5×力量","cost":"耐力10","interval":"3.0s","hit_formula":"70+1.0×耐力","category":"主动"},
            {"name":"缩壳","type":"防御","formula":"8+1.0×耐力/秒","cost":"耐力8","interval":"5.0s(冷却)","hit_formula":"","category":"主动"},
        ],
        "passives": [{"name":"凝胶身体","effect":"钝伤减半"}],
    },
    "哥布林": {
        "skills": [
            {"name":"匕首","type":"刺击","formula":"12+1.5×速度+1.0×力量","cost":"耐力8","interval":"2.0s","hit_formula":"70+2.0×速度","category":"主动"},
            {"name":"陷阱","type":"钝击","formula":"15+1.0×智力(固定)","cost":"耐力20","interval":"8.0s","hit_formula":"120","category":"主动"},
            {"name":"魔法护盾","type":"防御","formula":"8+1.0×智力+0.5×法量/秒","cost":"蓝0.8/0.1s","interval":"持续","hit_formula":"","category":"主动"},
        ],
        "passives": [{"name":"狡诈","effect":"先手时命中+15%"}, {"name":"工程天赋","effect":"工程建造速度+0.5天/每日"}],
        # 双倍开局时第二只哥布林用弓箭手技能组（战士+弓箭手搭配）
        "alt_skills": [
            {"name":"短弓射击","type":"刺击","formula":"15+2.0×速度+0.5×力量","cost":"耐力8","interval":"3.0s","hit_formula":"75+2.5×速度","category":"主动"},
            {"name":"淬毒箭","type":"刺击","formula":"20+2.5×速度+1.0×智力","cost":"耐力18","interval":"6.0s","hit_formula":"80+2.0×速度","category":"主动"},
            {"name":"闪避步法","type":"防御","formula":"10+2.0×速度/秒","cost":"耐力0.4/0.1s","interval":"持续","hit_formula":"","category":"主动"},
        ],
        "alt_passives": [{"name":"远程狙击","effect":"远程攻击伤害+15%，命中+10%"}, {"name":"工程天赋","effect":"工程建造速度+0.5天/每日"}],
    },
    "史莱姆": {
        "skills": [
            {"name":"撞击","type":"钝击","formula":"10+1.5×耐力+0.5×力量","cost":"耐力10","interval":"3.0s","hit_formula":"70+1.0×耐力","category":"主动"},
            {"name":"缩壳","type":"防御","formula":"8+1.0×耐力/秒","cost":"耐力8","interval":"5.0s(冷却)","hit_formula":"","category":"主动"},
        ],
        "passives": [{"name":"凝胶身体","effect":"钝伤减半"}],
        # 双倍开局时第二只史莱姆用酸液技能组
        "alt_skills": [
            {"name":"酸液喷射","type":"法术","formula":"15+2.0×智力","cost":"蓝10","interval":"3.5s","hit_formula":"70+2.0×智力","category":"主动"},
            {"name":"分裂","type":"防御","formula":"下次受击减半后回复8+1.0×耐力","cost":"耐力10","interval":"12.0s(冷却)","hit_formula":"","category":"主动"},
        ],
        "alt_passives": [{"name":"酸性体质","effect":"受击时对攻击者造成2+0.3×智力酸蚀伤害"}],
    },
}

def _assign_starter_skills(char, provided_skills=None, provided_passives=None):
    """给角色分配初始技能。优先用提供的，否则查物种默认。"""
    skills_data = provided_skills
    passives_data = provided_passives
    if not skills_data and not passives_data:
        starter = SPECIES_STARTER_SKILLS.get(char["species"])
        if starter:
            skills_data = starter.get("skills", [])
            passives_data = starter.get("passives", [])
    if skills_data:
        for s in skills_data:
            sk = json.loads(json.dumps(SKILL_TEMPLATE))
            sk["id"] = _skill_id()
            sk.update(s)
            char["skills"].append(sk)
    if passives_data:
        for p in passives_data:
            sk = json.loads(json.dumps(SKILL_TEMPLATE))
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

def _ensure_melee_skill(char):
    """确保角色至少有一个近战攻击技能（法师/射手给一个极弱的应急技）"""
    # 近战关键字：技能名含这些才算真正的近战攻击
    melee_keywords = ("杖", "拳", "踢", "咬", "爪", "刀", "剑", "斧", "锤", "棍", "匕", "砍", "劈", "砸", "撞", "尾", "撕")
    ranged_keywords = ("弓", "射", "弹", "息", "球", "箭", "矢", "枪")
    for s in char.get("skills", []):
        name = s.get("name", "")
        stype = s.get("type", "")
        # 跳过防御/被动技能
        if stype == "防御" or s.get("category") == "被动":
            continue
        # 有近战关键字 → 有近战
        if any(kw in name for kw in melee_keywords):
            return
        # 远程关键字 → 跳过
        if any(kw in name for kw in ranged_keywords):
            continue
        # 钝击且无名显远程特征 → 算近战
        if stype == "钝击":
            return
    # 根据角色定位给一个极弱的近战应急技能
    stats = char.get("stats", {})
    spd = stats.get("SPD", 3)
    str_ = stats.get("STR", 3)
    int_ = stats.get("INT", 3)
    # 先根据已有技能名判断定位（比属性更准）
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
    sk = json.loads(json.dumps(SKILL_TEMPLATE))
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

# ── 会话管理 ──

def new_session(world_setting=None, player_name="小魔王", char_name="小魔王", char_species="人类", char_coeff=1.3, char_stats=None, char_skills=None, char_passives=None):
    sid = uuid.uuid4().hex[:12]
    world = world_setting or DEFAULT_WORLD
    sys_content = SYS.replace("{WORLD_SETTING}", world)
    sys_content = sys_content.replace("{PLAYER_NAME}", player_name)
    sys_content = sys_content.replace("{CHAR_NAME}", char_name)
    sys_content = sys_content.replace("{CHAR_SPECIES}", char_species)
    main_char = _make_char(char_name, char_species, char_coeff, 1)
    if char_stats:
        for k in ATTR_KEYS:
            if k in char_stats and isinstance(char_stats[k], (int, float)):
                main_char["stats"][k] = int(char_stats[k])
        # 预设角色不减自由点（属性已定好）
        main_char["free_points"] = 0
    # 分配初始技能
    _assign_starter_skills(main_char, char_skills, char_passives)
    _ensure_melee_skill(main_char)
    # 哥布林/史莱姆开局双倍——弱小物种以数量取胜（第二只不同职业避免同质化）
    extra_chars = []
    if char_species in ("哥布林", "史莱姆"):
        twin_name = char_name + "2号" if char_species == "史莱姆" else char_name.replace("吱吱", "嘎嘎") if "吱吱" in char_name else char_name + "弟"
        twin = _make_char(twin_name, char_species, char_coeff, 1)
        if char_stats:
            for k in ATTR_KEYS:
                if k in char_stats and isinstance(char_stats[k], (int, float)):
                    twin["stats"][k] = int(char_stats[k])
            twin["free_points"] = 0
        # 第二只用 alt 技能组（哥布林弓箭手 / 史莱姆酸液）
        alt_starter = SPECIES_STARTER_SKILLS.get(char_species, {})
        alt_skills = alt_starter.get("alt_skills", char_skills)
        alt_passives = alt_starter.get("alt_passives", char_passives)
        _assign_starter_skills(twin, alt_skills, alt_passives)
        _ensure_melee_skill(twin)
        extra_chars.append(twin)
        # 职业提示（友好）
        role_hint = f"（{char_species=='哥布林' and '战士' or '物理'} + {char_species=='哥布林' and '弓箭手' or '酸液'} 搭配）"
        sys_content += f"\n\n⚠️ 由于选择了{char_species}（弱小物种），开局额外获得了一只 {twin_name} {role_hint}。你有两只{char_species}可以同时出战。"
    s = {
        "id": sid, "title": "新冒险",
        "world_setting": world,
        "player_name": player_name,
        "day": 1, "days_until_attack": 5, "raid_wave": 1,
        "events": [],
        "messages": [{"role": "system", "content": sys_content}],
        "characters": [main_char] + extra_chars,
        "active_char_id": main_char["id"],
        "constructions": [],
        "explored_today": [],
        "unlocked_equipment": [e["id"] for e in _equipment_by_source.get("starting", [])],
    }
    # 开局自动装备破烂
    starting_weapons = [e for e in _equipment_by_source.get("starting", []) if e["slot"] == "weapon"]
    starting_armors = [e for e in _equipment_by_source.get("starting", []) if e["slot"] == "armor"]
    starting_accessories = [e for e in _equipment_by_source.get("starting", []) if e["slot"] == "accessory"]
    if starting_weapons:
        main_char["equipment"]["weapon"] = random.choice(starting_weapons)["id"]
    if starting_armors:
        main_char["equipment"]["armor"] = random.choice(starting_armors)["id"]
    if starting_accessories:
        main_char["equipment"]["accessory"] = random.choice(starting_accessories)["id"]
    sessions[sid] = s
    return s

def _save(s):
    (BASE / "saves" / f"{s['id']}.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 自动注册到存档索引（不重复添加）
    idx = _load_saves_index()
    if not any(e.get("session_id") == s["id"] or e.get("file") == f"{s['id']}.json" for e in idx):
        chars = s.get("characters", [])
        char_desc = ", ".join(f"{c['name']}(Lv.{c['level']})" for c in chars[:5])
        idx.append({
            "file": f"{s['id']}.json",
            "name": s.get("title", "新冒险"),
            "saved_at": datetime.datetime.now().isoformat(),
            "session_id": s["id"],
            "title": s.get("title", "新冒险"),
            "characters": char_desc,
            "msg_count": len(s.get("messages", [])),
            "auto": True
        })
        _save_saves_index(idx)

def _log_event(sess, etype, msg, data=None):
    """记录游戏事件到日志"""
    sess.setdefault("events", []).append({
        "day": sess.get("day", 1),
        "type": etype,
        "msg": msg,
        "data": data or {},
    })

def _load(sid):
    p = BASE / "saves" / f"{sid}.json"
    if p.exists():
        try:
            d = json.loads(p.read_text("utf-8"))
            # 兼容旧存档
            if "stats" in d and "characters" not in d:
                c = _make_char("小魔王", "人类", 1.3, 1)
                c["stats"] = {k: d["stats"].get(k, 3) for k in ATTR_KEYS}
                c["free_points"] = d["stats"].get("free", 3)
                c["level"] = d.get("level", 1)
                c["exp"] = d.get("exp", 0)
                d["characters"] = [c]
                d["active_char_id"] = c["id"]
                del d["stats"]
            sessions[sid] = d
            return d
        except Exception:
            pass
    return None

def _advance_constructions(sess):
    """每日推进工程建造进度——第一个在建工程+1天（哥布林被动+0.5，多只不叠加）"""
    cons = sess.get("constructions", [])
    building = [c for c in cons if c.get("status") == "building"]
    if not building:
        return
    # 检查是否有工程天赋被动——不叠加（有一只就算）
    chars = sess.get("characters", [])
    has_engineering = False
    for ch in chars:
        for p in ch.get("passives", []):
            if "工程" in (p.get("effect", "") or "") or "建造速度" in (p.get("effect", "") or ""):
                has_engineering = True
                break
        if has_engineering:
            break
    bonus = 0.5 if has_engineering else 0
    # 推进第一个在建工程
    first = building[0]  # 按队列顺序（加入顺序）
    first["build_progress"] = first.get("build_progress", 0) + 1 + bonus
    if first["build_progress"] >= first.get("build_total", 1):
        first["status"] = "built"
        first["built_day"] = sess.get("day", 1)
        _log_event(sess, "build_complete", f'🏗️ {first["name"]} 建造完成！', {"construction": first["name"], "day": sess.get("day", 1)})

def _check_births(sess):
    """每日检查怀孕魔物是否到预产期，到期自动生产"""
    chars = sess.get("characters", [])
    day = sess.get("day", 1)
    births = []
    for c in chars:
        preg = c.get("pregnant")
        if preg and day >= preg.get("due_day", 999):
            father_name = preg.get("father_name", "?")
            father_species = preg.get("father_species", c["species"])
            child_name = c["name"][0] + father_name[0] + "崽"
            # 跨物种/魔王配种：后代继承怀孕方的物种
            child_species = c["species"]
            child = _make_char(child_name, child_species, c.get("species_coeff", 1.3), 1)
            for k in ATTR_KEYS:
                father = next((ch for ch in chars if ch["name"] == father_name), None)
                if father:
                    child["stats"][k] = max(1, int((c["stats"].get(k,3) + father["stats"].get(k,3)) / 2 + random.randint(-1,1)))
                else:
                    # 父方是魔王——后代属性=母方+随机加成
                    child["stats"][k] = max(1, c["stats"].get(k,3) + random.randint(0,2))
            child["free_points"] = 3
            # 继承随机技能
            father_obj = next((ch for ch in chars if ch["name"] == father_name), None)
            srcs = [(c, "skills")]
            if father_obj:
                srcs.append((father_obj, "passives"))
            for src, dst_key in srcs:
                pool = src.get(dst_key, []) if dst_key == "skills" else src.get("skills", []) + src.get("passives", [])
                if pool:
                    pick = random.choice(pool)
                    sk = json.loads(json.dumps(SKILL_TEMPLATE))
                    sk["id"] = _skill_id(); sk.update(pick); sk["level"] = 1
                    if dst_key == "skills": child["skills"].append(sk)
                    else: child.setdefault("passives", []).append(sk)
            _assign_starter_skills(child)
            _ensure_melee_skill(child)
            chars.append(child)
            cross_tag = f"（{father_species}×{child_species}混血）" if father_species != child_species else ""
            births.append(f'{c["name"]} 生下了 {child_name}{cross_tag}！')
            _log_event(sess, "birth", f'{c["name"]} → {child_name}', {"child": child_name, "species": child_species, "mother": c["name"], "father": father_name, "father_species": father_species})
            del c["pregnant"]  # 清除怀孕状态
    return births

# ── 请求模型 ──

class ChatReq(BaseModel):
    message: str
    session_id: str = ""

class SetReq(BaseModel):
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    nsfw: bool = False

class CharAddReq(BaseModel):
    name: str
    species: str = "人类"
    species_coeff: float = 1.3
    level: int = 1
    stats: dict = {}

class SkillCustomReq(BaseModel):
    description: str

class SkillAddReq(BaseModel):
    skill: dict

# ── 解析 CHAR_ADD / LEVEL_UP ──

def _validate_narrative(text: str, chars: list, sess: dict) -> str:
    """检查 AI 叙述是否与角色数据一致，不一致则追加系统提示"""
    if not text:
        return text
    warnings = []
    # 说「升级」但没 [LEVEL_UP] 标签？
    level_words = ['升级', '升到', '等级', '变强', '成长了', '升了']
    has_level_talk = any(w in text for w in level_words)
    has_level_tag = '[LEVEL_UP:' in text
    if has_level_talk and not has_level_tag:
        warnings.append('💡 系统：检测到升级描述但未使用 [LEVEL_UP] 标签——角色面板不会更新。下次请带上标签。')

    # 说「加入/新成员」但没 [CHAR_ADD] 标签？
    char_words = ['加入', '投靠', '出现了一只', '来了一个', '新的魔物', '新成员', '收服']
    has_char_talk = any(w in text for w in char_words)
    has_char_tag = '[CHAR_ADD:' in text
    if has_char_talk and not has_char_tag:
        warnings.append('💡 系统：检测到新角色描述但未使用 [CHAR_ADD] 标签——面板不会显示。下次请带上标签。')

    # 说战斗/攻击但没用 [DMG] 块？
    fight_words = ['挥爪', '咬', '扑', '撞', '斩', '刺', '射', '撕', '魔法', '吐息', '龙息','抓','踢','打','攻击','发起']
    has_fight_talk = any(w in text for w in fight_words)
    has_dmg_block = '[DMG:' in text
    if has_fight_talk and not has_dmg_block:
        warnings.append('⚠️ 系统：检测到战斗描述但未使用 [DMG] 计算块——伤害未按公式计算，结果无效。')

    # 说属性数值但与实际不符？
    for c in chars:
        # 检测「Lv.X」或「等级X」与实际是否一致
        lv_matches = re.findall(rf'{re.escape(c["name"])}.*?[Ll][Vv]\\.?\\s*(\\d+)', text)
        for m in lv_matches:
            claimed = int(m)
            actual = c["level"]
            if claimed != actual:
                warnings.append(f'⚠️ 系统：AI 说 {c["name"]} 是 Lv.{claimed}，实际数据为 Lv.{actual}。面板数据为准。')
                break

    # 提到不在队伍里的角色？
    owned_names = {c["name"] for c in chars}
    owned_species = {c["species"] for c in chars}
    # 检测「猫龙」「幼龙」「史莱姆」等物种名——如果在叙述中作为我方魔物出现但不在队伍里
    for sp in ["猫龙","幼龙","触手怪","石像鬼","杀人兔","野狼","史莱姆","哥布林","蝙蝠","蛇"]:
        if sp in text and sp not in owned_species:
            # 检查是否作为我方魔物被提到（不是入侵者）
            if f"你的{sp}" in text or f"自己的{sp}" in text or f"{sp}蹭" in text or f"{sp}摇" in text or f"{sp}望" in text:
                warnings.append(f'💡 系统：提到了{sp}但我方队伍中没有{sp}。请只使用 [队伍] 中列出的角色。')

    if warnings:
        # 警告写入事件日志而非泄漏到叙事文本
        for w in warnings:
            _log_event(sess, "system_warn", w[:200], {"warning": w[:200]})
    return text

CHAR_ADD_RE = re.compile(
    r'\[CHAR_ADD:\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*'
    r'END:(\d+)\s+STR:(\d+)\s+SPD:(\d+)\s+DEF:(\d+)\s+INT:(\d+)\s+MP:(\d+)\s+WIL:(\d+)\s*'
    r'(?:\|\s*(.+?))?\]',
    re.IGNORECASE
)

SKILL_PARSE_RE = re.compile(
    r'([^:;]+):([^:;]+):([^:;]+):([^:;]+):([^:;]+)(?::([^:;]+))?'
)

LEVEL_UP_RE = re.compile(
    r'\[LEVEL_UP:\s*([^|]+?)\s*\|\s*(\d+)\s*\]',
    re.IGNORECASE
)

CONSTRUCTION_DISCOVER_RE = re.compile(
    r'\[CONSTRUCTION_DISCOVER:\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\]',
    re.IGNORECASE
)

CONSTRUCTION_UPGRADE_RE = re.compile(
    r'\[CONSTRUCTION_UPGRADE:\s*([^|]+?)\s*\|\s*(\d+)\s*\]',
    re.IGNORECASE
)

def _parse_char_add(text: str) -> tuple:
    """返回 (clean_text, char_data_or_None, level_ups, construction_discovers, construction_upgrades)"""
    char_data = None
    level_ups = []
    con_discovers = []
    con_upgrades = []

    m = CHAR_ADD_RE.search(text)
    if m:
        name = m.group(1).strip()
        species = m.group(2).strip()
        stats = {
            "END": int(m.group(3)), "STR": int(m.group(4)), "SPD": int(m.group(5)),
            "DEF": int(m.group(6)), "INT": int(m.group(7)), "MP": int(m.group(8)),
            "WIL": int(m.group(9)),
        }
        skills_raw = m.group(10)
        char_data = {
            "name": name, "species": species, "stats": stats,
            "skills_raw": skills_raw.strip() if skills_raw else "",
        }
        text = text[:m.start()] + text[m.end():]

    # 解析 LEVEL_UP
    for lm in LEVEL_UP_RE.finditer(text):
        level_ups.append({"name": lm.group(1).strip(), "new_level": int(lm.group(2))})
        text = text[:lm.start()] + text[lm.end():]

    # 解析 CONSTRUCTION_DISCOVER
    for cm in CONSTRUCTION_DISCOVER_RE.finditer(text):
        con_discovers.append({
            "name": cm.group(1).strip(),
            "icon": cm.group(2).strip(),
            "type": cm.group(3).strip(),
            "description": cm.group(4).strip(),
            "effect": cm.group(5).strip(),
            "build_days": int(cm.group(6)),
            "max_count": int(cm.group(7)),
        })
        text = text[:cm.start()] + text[cm.end():]

    # 解析 CONSTRUCTION_UPGRADE
    for um in CONSTRUCTION_UPGRADE_RE.finditer(text):
        con_upgrades.append({
            "name": um.group(1).strip(),
            "new_max": int(um.group(2)),
        })
        text = text[:um.start()] + text[um.end():]

    return text.strip(), char_data, level_ups, con_discovers, con_upgrades

def _make_skills_from_raw(raw: str) -> list:
    """从原始技能字符串解析技能列表"""
    skills = []
    if not raw:
        return skills
    for sm in SKILL_PARSE_RE.finditer(raw):
        s = json.loads(json.dumps(SKILL_TEMPLATE))
        s["id"] = _skill_id()
        s["name"] = sm.group(1).strip()
        s["type"] = sm.group(2).strip()
        s["formula"] = sm.group(3).strip()
        s["cost"] = sm.group(4).strip()
        s["interval"] = sm.group(5).strip()
        s["hit_formula"] = (sm.group(6) or "").strip()
        skills.append(s)
    return skills

# ── 兼容旧存档 ──

NO_KEY_MSG = """🔥💢 本大爷没有 API key 用不了！

去 ⚙️设置 页面填你的 LLM API key（DeepSeek/OpenAI 兼容格式即可）。
免费获取 DeepSeek key：https://platform.deepseek.com/api_keys"""

# ══════════════════════════════════════════════
# API 路由
# ══════════════════════════════════════════════

@app.get("/")
def index():
    return FileResponse(BASE / "index.html", headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    })

# ── 聊天 ──

@app.post("/api/chat")
def chat(req: ChatReq):
    sess = sessions.get(req.session_id) or new_session()
    chars = sess.get("characters", [])
    active = next((c for c in chars if c["id"] == sess.get("active_char_id")), chars[0] if chars else None)

    # 构建角色提示
    hint_parts = []
    for c in chars:
        st = c["stats"]
        line = (
            f"[{c['name']} Lv.{c['level']} {c['species']}] "
            + " / ".join(f"{k}:{v}" for k, v in st.items())
            + f" | 自由:{c['free_points']} | 技能点:{c['pending_skill_points']}"
            + (f" | 技能:{','.join(s['name'] for s in c['skills'])}" if c['skills'] else "")
            + (f"\n  技能详情:" + "; ".join(
                f"{s['name']}「{s.get('type','?')}」" + 
                f"伤害={s.get('formula','?')}" +
                f" 消耗={s.get('cost','?')}" +
                f" 间隔={s.get('interval','?')}" +
                (f" 命中={s.get('hit_formula','?')}" if s.get('hit_formula') else "")
                for s in c['skills']
            ) if c['skills'] else "")
        )
        # 装备信息
        eq = c.get("equipment", {})
        if eq:
            eq_names = []
            for slot_key in ("weapon", "armor", "accessory"):
                eq_id = eq.get(slot_key)
                if eq_id:
                    eq_item = next((e for e in _equipment_pool if e["id"] == eq_id), None)
                    eq_names.append(f"{slot_key}:{eq_item['name']}" if eq_item else f"{slot_key}:?")
            if eq_names:
                line += f"\n  装备:{', '.join(eq_names)}"
        # 怀孕状态标记
        if c.get("pregnant"):
            due = c["pregnant"]["due_day"]
            line += f"\n  🤰怀孕中（预产期第{due}天）——所有伤害-60%，无法闪避"
        hint_parts.append(line)
    hint = "\n".join(hint_parts)

    # 上下文截断 —— 防止消息无限增长撞 128K 上限
    summary_text = _trim_and_summarize(sess)

    msgs = sess["messages"].copy()
    # 使用会话保存的世界观重建 system prompt（角色信息动态追加）
    world = sess.get("world_setting", DEFAULT_WORLD)
    day = sess.get("day", 1)
    dta = sess.get("days_until_attack", 5)
    nsfw_on = os.getenv("NSFW_ENABLED", "") == "true"
    if nsfw_on:
        nsfw_rules = "开放模式——默认战斗/探索/经营为主，但允许成人内容。\n当玩家使用配种功能时，魔王在育成室内亲自监督整个交配过程。GM需详细描写全过程：\n【输出长度】\n色情场景每段1500字以上——不设上限，详细描写每一个动作、反应、感官细节，不跳过任何阶段。平时每段150-250字，色情场景必须大幅扩展篇幅。\n【写作要求】\n- 使用直白的福瑞生理词汇：唧唧/鞘/前液/后穴/肉垫/乳头/精液等，不绕弯\n- 描写兽化体征细节：毛的炸起/服帖、耳朵的抖动/耷拉、尾巴的缠绕/绷直、肉垫的温热/湿润、角的敏感反应\n- 加入拟声词增加临场感：噗噜/咕啾/啵/嘶/哗\n- 句子长短混搭（短句≤30%），连续三个短句必须接中长句\n- 禁止AI写作腔：「不是X而是Y」「首先其次最后」「总而言之」等一律禁用\n- ⚠️ 铁律——「不是……而是……」句式为最高禁令：遇到对比/纠正场景时，必须拆成两句独立陈述。例：不说「这不是刀，而是剑」→ 说「这不是刀。是一把剑。」一旦出现此句式，整段作废重写。\n- 事后温存收尾，不突然切场景\n【角色反应】\n- 被选中的魔物害羞脸红、耳朵耷拉、尾巴不安地摆动，但内心欢喜——绝不拒绝魔王的任何要求\n- 魔王主导节奏，魔物顺从配合"
        nsfw_breeding = "⚠️ NSFW模式已开启——GM必须详细描写交配过程（见上方内容基调）。"
    else:
        nsfw_rules = "全年龄向——战斗、探索、经营、日常。严禁任何色情描写。\n当玩家使用配种功能时：魔物们会害羞地躲进育成室并关上门。GM只需描述「它们红着脸进了育成室，门关上了」然后直接跳到结果（蛋/幼崽诞生），绝不可描写交配过程。如果玩家试图窥探或引导色情内容，GM要主动规避：「育成室的门紧锁着，你听到里面传来窸窸窣窣的声音...」然后跳过。"
        nsfw_breeding = "这是宝可梦式的孵蛋系统——不描写交配过程，只叙述结果（蛋/幼崽诞生）。GM不得主动引导或描写色情内容。"
    base_sys = SYS.replace("{WORLD_SETTING}", world).replace("{NSFW_RULES}", nsfw_rules).replace("{NSFW_BREEDING}", nsfw_breeding)
    # 注入历史摘要（截断后的旧消息压缩）
    base_sys = _inject_summary(base_sys, sess)
    day_info = f"\n[第{day}天] 距离冒险者来袭还有{dta}天。" if dta > 0 else f"\n[第{day}天] ⚠️ 冒险者今天来袭！"
    # 防御工事信息
    con_list = [c for c in sess.get("constructions", []) if c.get("status") == "built"]
    con_info = ""
    if con_list:
        con_lines = []
        for c in con_list:
            eff = c.get("effect", {})
            eff_desc = []
            if "melee_climb_time" in eff:
                eff_desc.append(f"近战攀爬={eff['melee_climb_time']}")
            if "enemy_ranged_hit" in eff:
                eff_desc.append(f"敌远程命中{eff['enemy_ranged_hit']}")
            if "ally_ranged_hit" in eff:
                eff_desc.append(f"我方远程命中{eff['ally_ranged_hit']}")
            if "durability" in eff:
                eff_desc.append(f"耐久{eff['durability']}")
            if "damage" in eff:
                eff_desc.append(f"伤害={eff['damage']}")
            if "uses" in eff:
                eff_desc.append(f"剩余次数={c.get('uses_left','?')}")
            if "immobilize" in eff:
                eff_desc.append(f"效果={eff['immobilize']}")
            if "blind" in eff:
                eff_desc.append(f"效果={eff['blind']}")
            con_lines.append(f"  {c['icon']} {c['name']}（{c['type']}）: {', '.join(eff_desc)}")
        con_info = "\n[防御工事]\n" + "\n".join(con_lines) + "\n⚠️ 战斗时GM必须考虑这些工事的效果。城墙上的我方远程命中+15%、敌方远程-20%、近战需攀爬(刺客SPD减免)。"
    msgs[0] = {"role": "system", "content": base_sys + day_info + con_info + f"\n[队伍]\n{hint}\n[当前活跃] {active['name'] if active else '无'}"}
    # 处理 /day 命令 —— 推进天数
    chars_updated = False
    day_advanced = False
    user_msg = req.message.strip()
    if user_msg.startswith('/day') or user_msg.startswith('/次日') or user_msg.startswith('/过天'):
        day_advanced = True
        action = user_msg.replace('/day','').replace('/次日','').replace('/过天','').strip() or '锻炼'
        sess["day"] = sess.get("day", 1) + 1
        sess["days_until_attack"] = max(0, sess.get("days_until_attack", 5) - 1)
        dta = sess["days_until_attack"]
        day_msg = ""  # 初始化为空，各阶段追加
        # 工程建造进度推进
        _advance_constructions(sess)
        # 每日恢复 → HP/护甲/体力/精神回满
        _daily_recovery_all(sess)
        # 检查怀孕到期 → 自动生产
        births = _check_births(sess)
        if births:
            day_msg = "\n".join(f"[BIRTH] {b}" for b in births)
        # 怀孕期间：可做日常活动但不能剧烈战斗（伤害-60%）
        if active and active.get("pregnant"):
            due = active["pregnant"]["due_day"]
            day_msg = (day_msg or "") + f"\n🤰 {active['name']} 正在怀孕中（预产期第{due}天）——只能进行轻度日常活动，若参战伤害-60%。"
        # 日常活动 → 给活跃角色加经验
        exp_gain = max(3, int((30 - sess["day"] * 0.5) / max(1, active["level"] * 0.3))) if active else 0
        old_level = active["level"] if active else 1
        if active and action in ('锻炼','训练','train'):
            active["exp"] = active.get("exp", 0) + exp_gain
            # 检查升级 (简化：每100×等级 exp 升一级)
            need_exp = 100 * active["level"]
            while active["exp"] >= need_exp:
                active["level"] += 1
                active["exp"] -= need_exp
                active["free_points"] = active.get("free_points", 0) + 1
                active["pending_skill_points"] = active.get("pending_skill_points", 0) + 1
                need_exp = 100 * active["level"]
            # 猫龙 Lv.10 进化事件
            if active and active.get("species") == "猫龙" and active["level"] >= 10 and not active.get("evolved"):
                active["evolved"] = True
                active["evolve_forms"] = ["龙人形态", "巨猫龙形态"]
                active["evolve_form"] = None  # 等待玩家选择
                day_msg = (day_msg or '') + f'\\n[EVOLVE] {active["name"]} 体内的龙族血脉觉醒了！它可以在两种形态间自由切换：\\n'
                day_msg += '- **龙人形态**：半直立，智力+2 法量+2，解锁高阶龙息法术\\\\n'
                day_msg += '- **巨猫龙形态**：体型暴增，力量+2 耐力+2，物理伤害大幅提升\\n'
                day_msg += '⚠️ 请 GM 叙述进化场景，并让玩家选择形态（可在角色面板切换）。'
                _log_event(sess, "evolve", f'{active["name"]} 进化——可选龙人/巨猫龙', {"char": active["name"]})
                chars_updated = True
            chars_updated = True
        # 构建日常叙述 prompt
        activity_desc = {
            '锻炼':'带领魔物们在地下城训练场挥汗如雨',
            '训练':'带领魔物们在地下城训练场挥汗如雨',
            'train':'带领魔物们在地下城训练场挥汗如雨',
            '巡逻':'派出魔物巡视地下城周边',
            '休息':'让魔物们好好休息了一天',
            '研究':'在地下城图书室钻研远古典籍',
            '净化':'在地下城圣泉进行净化仪式',
            '配种':'将两只魔物送入育成室',
            '探索':'派出魔物深入地下城未知区域探索',
        }.get(action, f'进行了{action}')
        # 净化：清除活跃角色的负面状态
        if action.startswith('净化') and active:
            removed = []
            if active.get('cursed'): del active['cursed']; removed.append('诅咒')
            if active.get('debuff'): del active['debuff']; removed.append('减益')
            if active.get('poisoned'): del active['poisoned']; removed.append('中毒')
            if removed:
                day_msg = f'[PURIFY] {active["name"]} 被净化了——移除了 {", ".join(removed)}。'
                _log_event(sess, "purify", f'{active["name"]} 净化了 {", ".join(removed)}', {"char": active["name"]})
        # 配种：解析 父=xxx 母=yyy（无生殖隔离，跨物种成功率降低，魔王操魔物100%受孕）
        if action.startswith('配种'):
            import re as _re
            father_name = _re.search(r'父[=＝]([^\s母]+)', user_msg)
            mother_name = _re.search(r'母[=＝]([^\s父]+)', user_msg)
            father = mother = None
            father_is_player = mother_is_player = False
            if father_name and mother_name:
                fn, mn = father_name.group(1).strip(), mother_name.group(1).strip()
                player_name = sess.get("player_name", "小魔王")
                if fn == player_name:
                    father_is_player = True
                if mn == player_name:
                    mother_is_player = True
                for c in chars:
                    if c["name"] == fn: father = c
                    if c["name"] == mn: mother = c
            if (father or father_is_player) and (mother or mother_is_player):
                # 不能自己配自己
                if father and mother and father["id"] == mother["id"]:
                    day_msg = '⚠️ 不能自己配自己！'
                # 检查魔物方是否怀孕
                elif father and father.get("pregnant"):
                    day_msg = f'⚠️ {father["name"]} 正在怀孕中，不能参与配种。'
                elif mother and mother.get("pregnant"):
                    day_msg = f'⚠️ {mother["name"]} 正在怀孕中，不能参与配种。'
                else:
                    # 计算受孕成功率
                    if father_is_player or mother_is_player:
                        success_rate = 1.0  # 魔王操魔物100%
                    elif father["species"] == mother["species"]:
                        success_rate = 1.0  # 同物种100%
                    else:
                        # 跨物种：系数差距越大成功率越低
                        gap = abs(father.get("species_coeff", 1.3) - mother.get("species_coeff", 1.3))
                        if gap <= 0.2:
                            success_rate = 0.8
                        elif gap <= 0.5:
                            success_rate = 0.5
                        else:
                            success_rate = 0.3
                    # 确定怀孕方（母方优先；如果母方是玩家则父方怀）
                    carrier = mother if mother else father  # 至少有一个是魔物
                    partner = father if mother else mother  # 另一个
                    partner_name = partner["name"] if partner else (fn if father_is_player else mn)
                    partner_species = partner.get("species", "魔王") if partner else "魔王"
                    # 受孕判定
                    if random.random() < success_rate:
                        # 计算怀孕天数：按怀孕方物种稀有度
                        coeff = carrier.get("species_coeff", 1.3)
                        if coeff <= 0.9:
                            gest_days = 1
                        elif coeff <= 1.0:
                            gest_days = 1
                        elif coeff <= 1.2:
                            gest_days = 2
                        elif coeff <= 1.3:
                            gest_days = 4
                        else:
                            gest_days = 3
                        due_day = sess["day"] + gest_days
                        carrier["pregnant"] = {
                            "father_name": partner_name,
                            "father_id": partner["id"] if partner else "",
                            "father_species": partner_species,
                            "due_day": due_day,
                            "is_player": father_is_player or mother_is_player,
                        }
                        child_name = (partner_name or "魔")[0] + carrier["name"][0] + "崽"
                        cross_note = f"（跨物种：{partner_species}×{carrier['species']}）" if (partner and partner.get("species") != carrier["species"]) or (father_is_player or mother_is_player) else ""
                        day_msg = f'[BREED] {carrier["name"]} 怀孕了！（另一方：{partner_name}）{cross_note}预计 {gest_days} 天后（第{due_day}天）生下 {child_name}。{carrier["name"]} 在怀孕期间战斗伤害-60%。'
                        _log_event(sess, "breed_start", f'{partner_name}+{carrier["name"]} → 怀孕 {gest_days}天', {"partner": partner_name, "carrier": carrier["name"], "due_day": due_day, "cross_species": bool(cross_note)})
                    else:
                        cross_info = f'{father.get("species","?")}×{mother.get("species","?")}' if not (father_is_player or mother_is_player) else "魔王×魔物"
                        day_msg = f'😿 配种失败……{cross_info} 的受孕率只有 {int(success_rate*100)}%，这次没怀上。可以改天再试试。'
            else:
                day_msg = '⚠️ 请至少指定一只魔物参与配种，用 /day 配种 父=名字 母=名字（魔王本人用「小魔王」）'
        # 重置每日探索记录
        sess["explored_today"] = []
        # 巡逻触发招募事件
        recruit_msg = ""
        if action.startswith('巡逻') and _recruit_pool:
            recruited = sess.get("recruited", [])
            available = [m for m in _recruit_pool if m["name"] not in recruited]
            if available and random.random() < 0.35:  # 35% 概率触发招募
                mon = random.choice(available)
                sess.setdefault("recruited", []).append(mon["name"])
                event_text = random.choice(RECRUIT_EVENTS).format(species=mon["species"])
                recruit_msg = (
                    f"\n[EVENT] 招募事件！{event_text}\n"
                    f"[CHAR_ADD: {mon['name']} | {mon['species']} | "
                    f"END:{mon['stats']['END']} STR:{mon['stats']['STR']} SPD:{mon['stats']['SPD']} "
                    f"DEF:{mon['stats']['DEF']} INT:{mon['stats']['INT']} MP:{mon['stats']['MP']} "
                    f"WIL:{mon['stats']['WIL']} | {mon['skills_raw']}]\n"
                    f"⚠️ 请 GM 叙述这段招募事件，然后系统会自动将 {mon['name']}（{mon['species']}）加入角色面板。"
                )
                _log_event(sess, "recruit", f"招募了 {mon['name']}（{mon['species']}）", {"char": mon['name'], "species": mon['species']})
        day_msg += f'[DAY_ADVANCE] 第{sess["day"]}天。{activity_desc}。' + recruit_msg + (f' ⚠️ 冒险者将在{dta}天后来袭！' if dta > 0 else ' ⚠️ 冒险者今天来袭！准备战斗！')
        # 第0天 → 程序模拟战斗（不再是 AI 叙事）
        if dta == 0:
            wave_idx = sess.get("raid_wave", 1) - 1
            combat_result = asyncio.run(_run_raid_combat(sess, wave_idx))
            combat_narrative = _build_combat_narrative(combat_result, sess["raid_wave"])
            # 将战斗结果追加到 day_msg，AI 只需润色叙事
            day_msg += f"\n\n[COMBAT_RESULT]\n{combat_narrative}\n\n⚠️ 以上是程序生成的战斗日志。请 GM 将其润色为一段精彩的战斗叙事（150-250字），不需要再计算伤害——所有数值已经由程序判定完毕。战斗结果：{'我方胜利' if combat_result['victor_team'] == 0 else '敌方胜利'}。"
        if active and action in ('锻炼','训练','train'):
            day_msg += f'\n[EXP] {active["name"]} 获得 {exp_gain} 经验。'
            _log_event(sess, "exp", f'{active["name"]} 获得 {exp_gain} 经验', {"char": active["name"], "exp": exp_gain})
            if active["level"] > old_level:
                day_msg += f' [LEVEL_UP: {active["name"]} | {active["level"]}] 升到了Lv.{active["level"]}！获得{active["level"] - old_level}自由属性点。'
                _log_event(sess, "level_up", f'{active["name"]} 升到 Lv.{active["level"]}', {"char": active["name"], "level": active["level"]})
                if active["pending_skill_points"] > 0:
                    day_msg += f' 技能点+{active["pending_skill_points"]}（每级获得）。'
        req.message = day_msg

    msgs.append({"role": "user", "content": req.message})

    if not os.getenv("OPENAI_API_KEY", ""):
        return {"narrative": NO_KEY_MSG, "session_id": sess["id"], "title": sess["title"], "characters_updated": False}

    try:
        c = _get_client()
        temp = float(os.getenv("LLM_TEMPERATURE", "0.85"))
        max_tok = int(os.getenv("LLM_MAX_TOKENS", "1024"))
        # 费用分层：非战斗 /day 用便宜模型
        cheap_model = os.getenv("LLM_CHEAP_MODEL", "")
        m = os.getenv("LLM_MODEL", "deepseek-chat")
        if cheap_model and day_advanced and dta > 0:
            m = cheap_model  # 日常锻炼/探索/配种——便宜模型就够了
        r = c.chat.completions.create(model=m, messages=msgs, temperature=temp, max_tokens=max_tok)
        reply = r.choices[0].message.content or "（翻白眼）"
    except Exception as e:
        reply = f"🔥💢 API 错误：{str(e)[:150]}"

    # 自动检查 AI 叙述一致性——说了升级/加角色但没用标签？
    reply = _validate_narrative(reply, chars, sess)

    # 解析 CHAR_ADD 和 LEVEL_UP 和 CONSTRUCTION
    clean_reply, char_data, level_ups, con_discovers, con_upgrades = _parse_char_add(reply)

    if char_data:
        new_char = _make_char(char_data["name"], char_data["species"], 1.3, 1)
        new_char["stats"] = char_data["stats"]
        new_char["free_points"] = 0
        new_char["skills"] = _make_skills_from_raw(char_data.get("skills_raw", ""))
        chars.append(new_char)
        chars_updated = True

    for lu in level_ups:
        target = lu["name"].strip().lower()
        for c in chars:
            if c["name"].strip().lower() == target:
                old_lv = c["level"]
                c["level"] = lu["new_level"]
                new_skill_points = c["level"] - old_lv
                if new_skill_points > 0:
                    c["pending_skill_points"] += new_skill_points
                chars_updated = True

    # 处理工程发现
    sess_constructions = sess.setdefault("constructions", [])
    for cd in con_discovers:
        # 生成唯一 ID
        con_id = f"con_explore_{len(sess_constructions)+1}_{cd['name'].replace(' ','_')[:10]}"
        sess_constructions.append({
            "id": con_id,
            "name": cd["name"],
            "type": cd["type"],
            "icon": cd["icon"],
            "description": cd["description"],
            "effect": cd["effect"],
            "build_days": cd["build_days"],
            "max_count": cd["max_count"],
            "status": "unbuilt",
            "source": "exploration",
        })
        _log_event(sess, "con_discover", f'探索发现了新工程蓝图：{cd["name"]}', {"name": cd["name"], "type": cd["type"]})
        chars_updated = True

    for cu in con_upgrades:
        target_name = cu["name"].strip()
        for c in sess_constructions:
            if c["name"].strip() == target_name:
                c["max_count"] = cu["new_max"]
                _log_event(sess, "con_upgrade", f'{target_name} 上限提升至 {cu["new_max"]}', {"name": target_name, "new_max": cu["new_max"]})
                chars_updated = True
                break

    sess["messages"] += [
        {"role": "user", "content": req.message},
        {"role": "assistant", "content": clean_reply},
    ]
    # raid 后自动重置：第0天战斗结束后，推进波次+重置倒计时
    if sess.get("days_until_attack", 5) == 0:
        wave_idx = sess.get("raid_wave", 1) - 1
        reset_days = RAID_WAVES[wave_idx]["reset_days"] if wave_idx < len(RAID_WAVES) else min(5 + wave_idx + 1, 15)
        sess["days_until_attack"] = reset_days
        sess["raid_wave"] = sess.get("raid_wave", 1) + 1
        chars_updated = True  # 确保前端刷新
        # 波次奖励：解锁高级装备 + 概率获得高级魔物
        _wave_reward_equipment(sess, sess["raid_wave"] - 1)  # 刚打完的波次
        _wave_reward_monster(sess, sess["raid_wave"] - 1)

    # 缓存历史摘要（如果有新截断的事件）
    if summary_text:
        _maybe_summarize_async(sess, summary_text)

    sessions[sess["id"]] = sess
    _save(sess)
    return {
        "narrative": clean_reply, "session_id": sess["id"], "title": sess["title"],
        "day": sess.get("day", 1), "days_until_attack": sess.get("days_until_attack", 5), "raid_wave": sess.get("raid_wave", 1),
        "characters_updated": chars if chars_updated else False,
    }


# ══════════════════════════════════════════
# 程序主导战斗引擎集成
# ══════════════════════════════════════════

async def _run_raid_combat(sess: dict, wave_idx: int) -> dict:
    """
    用程序模拟器运行一场 raid 战斗。
    返回: {narrative, victor_team, fighters_final, log, chars_updated}
    """
    wave = RAID_WAVES[wave_idx] if wave_idx < len(RAID_WAVES) else _gen_random_wave(sess["raid_wave"])
    chars = sess.get("characters", [])

    # ── 构建我方 Fighter 列表 ──
    our_fighters = []
    for c in chars:
        cfg = fighter_from_tavern_char(c, team=0, equipment_pool=_equipment_pool)
        skills = cfg.get("skills", [])
        # 补格挡技能（如果没有）
        if not any(s.get("type") == "defense" for s in skills):
            skills.append({"name": "格挡", "type": "defense", "formula": "0",
                          "cooldown": 0.5, "windup": 0.1, "recovery": 0.1})
        # 确保每个角色有至少一个近战攻击技能
        melee_types = ("slash", "pierce", "blunt")
        if not any(s.get("type") in melee_types for s in skills):
            skills.append({"name": "应急爪击", "type": "slash",
                          "formula": "10+1.5*STR+0.5*SPD",
                          "stamina_cost": 10, "cooldown": 2.0,
                          "windup": 0.3, "recovery": 0.5})
        f = Fighter(cfg, skills)
        our_fighters.append(f)

    # ── 构建敌方 Fighter 列表 ──
    enemy_fighters = []
    for e in wave["enemies"]:
        e_skills = parse_tavern_skills(e.get("skills_raw", ""))
        if not e_skills:
            e_skills = [{"name": "挥砍", "type": "slash", "formula": "15+2*STR+0.5*SPD",
                         "stamina_cost": 14, "cooldown": 3.0, "windup": 0.4, "recovery": 0.5}]
        if not any(s.get("type") == "defense" for s in e_skills):
            e_skills.append({"name": "格挡", "type": "defense", "formula": "0",
                           "cooldown": 0.5, "windup": 0.1, "recovery": 0.1})
        cfg = {
            "id": f"enemy_{uuid.uuid4().hex[:6]}",
            "name": e["name"], "level": e["level"],
            "species_coeff": 1.3,  # 人类
            "END": e["stats"].get("END", 3), "STR": e["stats"].get("STR", 3),
            "SPD": e["stats"].get("SPD", 3), "DEF": e["stats"].get("DEF", 2),
            "INT": e["stats"].get("INT", 2), "WIL": e["stats"].get("WIL", 3),
            "MP": e["stats"].get("MP", 2), "armor": e["level"] * 15, "team": 1,
        }
        enemy_fighters.append(Fighter(cfg, e_skills))

    # ── 环境: 地下城主场 ──
    env = "narrow"  # 地下城狭窄洞穴

    # ── 技能选择器 (默认本地规则，不调 API — 每 tick 调 API 太慢太贵) ──
    ai_picker = make_default_picker()

    # ── 运行 ──
    sim = CombatSim(our_fighters, enemy_fighters, environment=env, ai_skill_picker=ai_picker)
    result = await sim.run()

    # ── 写回 HP/耐力/护甲/精神 到 session ──
    for f in result.all_fighters_final:
        char_id = f["char_id"]
        # 我方角色
        for c in chars:
            if c["id"] == char_id:
                c["current_hp"] = round(f["hp"], 1)
                c["current_stamina"] = round(f["stamina"], 1)
                c["current_mana"] = round(f["mana"], 1)
                c["current_spirit"] = round(f["spirit"], 1)
                c["current_armor"] = round(f["armor"], 1)
                break

    return {
        "wave": wave,
        "victor_team": result.victor_team,
        "duration": result.duration,
        "total_ticks": result.total_ticks,
        "fighters_final": result.all_fighters_final,
        "log": result.log,
        "chars_updated": True,
    }


def _build_combat_narrative(combat_result: dict, wave_num: int) -> str:
    """将战斗日志转换为 AI 可读的叙事摘要"""
    lines = []
    wave = combat_result["wave"]
    lines.append(f"⚔️ 第{wave_num}波冒险者来袭——{wave['desc']}")
    lines.append(f"【敌方】{'、'.join(e['name']+'(Lv.'+str(e['level'])+')' for e in wave['enemies'])}")
    lines.append("")

    for entry in combat_result["log"]:
        cls = entry.get("cls", "")
        # 日志消息已经自带 emoji，不再重复添加前缀
        lines.append(f"[{entry['time']}s] {entry['msg']}")

    victor = "我方" if combat_result["victor_team"] == 0 else "敌方"
    lines.append(f"\n🏆 战斗结束——{victor}获胜！({combat_result['duration']}秒)")

    return "\n".join(lines)


def _daily_recovery_all(sess: dict):
    """每日恢复——所有角色 HP/护甲/体力回满"""
    for c in sess.get("characters", []):
        c["current_hp"] = None     # None = 满血
        c["current_stamina"] = None
        c["current_mana"] = None
        c["current_spirit"] = None
        c["current_armor"] = None

# ── 事件日志 ──

# ── 波次奖励 & 探索系统 ──

def _wave_reward_equipment(sess, wave):
    """波次胜利后解锁并发放高级装备"""
    if wave == 1:
        # 第1波：解锁 uncommon 及以下装备，随机给2件
        pool = [e for e in _equipment_pool if e.get("source") in ("wave", "exploration") and e["rarity"] in ("common", "uncommon")]
    elif wave == 2:
        # 第2波：解锁 rare 及以下
        pool = [e for e in _equipment_pool if e.get("source") in ("wave", "exploration") and e["rarity"] in ("common", "uncommon", "rare")]
    else:
        # 第3波+：解锁所有
        pool = [e for e in _equipment_pool if e.get("source") in ("wave", "exploration")]
    
    # 解锁这些装备
    unlocked = sess.setdefault("unlocked_equipment", [])
    for e in pool:
        if e["id"] not in unlocked:
            unlocked.append(e["id"])
    
    # 随机给2-3件装备到随机角色
    num = random.randint(2, min(3, len(pool)))
    chars = sess.get("characters", [])
    if chars and pool:
        given = random.sample(pool, min(num, len(pool)))
        for item in given:
            target = random.choice(chars)
            slot = item["slot"]
            target.setdefault("equipment", {"weapon": None, "armor": None, "accessory": None})
            target["equipment"][slot] = item["id"]
        _log_event(sess, "wave_reward", f'波次{wave}奖励：获得 {", ".join(i["name"] for i in given)}', {"wave": wave, "items": [i["name"] for i in given]})


def _gen_random_wave(wave_num):
    """3波后无限随机生成敌人"""
    import random as _r
    level_base = 8 + wave_num * 2  # 波4=Lv16, 波5=Lv18...
    count = min(2 + wave_num // 2, 8)  # 敌人数递增，最多8个
    roles = ["战士","弓箭手","法师","刺客","重装兵"]
    names_pool = ["精锐","老兵","冠军","精英","大师"]
    
    enemies = []
    for i in range(count):
        role = _r.choice(roles)
        level = level_base + _r.randint(-2, 3)
        name = f"{_r.choice(names_pool)}{role}"
        
        if role == "战士":
            stats = {"END":6,"STR":7,"SPD":5,"DEF":5,"INT":2,"MP":2,"WIL":5}
            skills = "重斩:斩击:30+2.5×力量+1.0×耐力:耐力22:4.0s; 格挡:防御:25+2.5×力量+1.5×耐力/秒:耐力0.5/0.1s:持续"
        elif role == "弓箭手":
            stats = {"END":4,"STR":4,"SPD":8,"DEF":3,"INT":3,"MP":3,"WIL":4}
            skills = "精准射击:刺击:25+3.0×速度+1.0×智力:耐力12:3.0s; 淬毒箭:刺击:18+2.0×速度+1.5×智力:蓝10:5.0s"
        elif role == "法师":
            stats = {"END":3,"STR":2,"SPD":4,"DEF":2,"INT":9,"MP":7,"WIL":6}
            skills = "火球术:法术:25+3.0×智力:蓝16:4.0s; 魔法盾:防御:8+1.0×智力+0.5×法量/秒:蓝8:5.0s"
        elif role == "刺客":
            stats = {"END":3,"STR":4,"SPD":9,"DEF":2,"INT":2,"MP":2,"WIL":4}
            skills = "暗杀:刺击:30+3.5×速度+1.0×力量:耐力15:3.0s; 闪避:防御:闪避+30(单次):耐力12:5.0s"
        else:  # 重装兵
            stats = {"END":8,"STR":6,"SPD":3,"DEF":7,"INT":1,"MP":1,"WIL":6}
            skills = "盾猛:钝击:20+1.5×力量+2.0×耐力:耐力18:4.0s; 格挡:防御:25+2.5×力量+1.5×耐力/秒:耐力0.5/0.1s:持续"
        
        # 按等级缩放属性（加法，避免后期指数爆炸）
        bonus = max(0, (level - 10))
        for k in stats:
            stats[k] = max(1, stats[k] + bonus)
        
        enemies.append({
            "name": name, "species": "人类", "level": level,
            "stats": stats, "skills_raw": skills
        })
    
    return {
        "wave": wave_num,
        "desc": f"第{wave_num}波——公会派出了更强大的冒险者队伍（{count}人，平均Lv.{level_base}）。",
        "enemies": enemies,
        "reset_days": min(5 + wave_num, 15)
    }



def _wave_reward_monster(sess, wave):
    """波次胜利后概率获得高级魔物（后期概率更高）"""
    base_prob = {1: 0.25, 2: 0.40, 3: 0.55}.get(wave, 0.55 + (wave - 3) * 0.1)
    if random.random() > min(base_prob, 0.70):
        return
    
    # 从物种库中选一个非杂鱼物种，给较高属性
    species_pool = [
        {"species": "幼龙", "coeff": 2.5, "stats": {"END": 7, "STR": 7, "SPD": 4, "DEF": 6, "INT": 5, "MP": 4, "WIL": 6}},
        {"species": "石像鬼", "coeff": 2.5, "stats": {"END": 7, "STR": 6, "SPD": 3, "DEF": 8, "INT": 2, "MP": 2, "WIL": 5}},
        {"species": "触手怪", "coeff": 2.0, "stats": {"END": 5, "STR": 5, "SPD": 6, "DEF": 3, "INT": 3, "MP": 4, "WIL": 4}},
        {"species": "猫龙", "coeff": 2.0, "stats": {"END": 5, "STR": 6, "SPD": 5, "DEF": 3, "INT": 6, "MP": 5, "WIL": 5}},
        {"species": "野狼", "coeff": 1.8, "stats": {"END": 4, "STR": 5, "SPD": 7, "DEF": 2, "INT": 1, "MP": 1, "WIL": 4}},
        {"species": "杀人兔", "coeff": 1.8, "stats": {"END": 3, "STR": 4, "SPD": 9, "DEF": 1, "INT": 1, "MP": 1, "WIL": 4}},
    ]
    sp = random.choice(species_pool)
    level = 3 + wave * 2
    # 随机名字
    names = {"幼龙": ["小焰", "晶翼", "铁颚"], "石像鬼": ["碎岩", "暗翼", "铁羽"],
             "触手怪": ["墨影", "深海", "缠绕"], "猫龙": ["影爪", "夜牙", "迅羽"],
             "野狼": ["灰鬃", "白牙", "裂风"], "杀人兔": ["血瞳", "飞腿", "雪球"]}
    name = random.choice(names.get(sp["species"], [sp["species"]]))
    # 构造 CHAR_ADD 标签——让系统自动加入角色面板
    from copy import deepcopy
    stats = deepcopy(sp["stats"])
    for k in stats:
        stats[k] = int(stats[k] * (0.8 + level * 0.2))
    char = _make_char(name, sp["species"], sp["coeff"], level)
    char["stats"] = stats
    _assign_starter_skills(char)
    _ensure_melee_skill(char)
    sess["characters"].append(char)
    _log_event(sess, "wave_monster", f'波次{wave}吸引了 {name}({sp["species"]} Lv.{level})', {"name": name, "species": sp["species"], "level": level})


# ── 探索 API ──

class ExploreRequest(BaseModel):
    char_id: str

@app.post("/api/session/{sid}/explore")
def explore_dungeon(sid: str, req: ExploreRequest):
    """派遣一个魔物探索地下城未知区域——每天每魔物限一次"""
    s = sessions.get(sid) or _load(sid)
    if not s:
        raise HTTPException(404, "会话不存在")
    char = next((c for c in s.get("characters", []) if c["id"] == req.char_id), None)
    if not char:
        raise HTTPException(400, "角色不存在")
    explored = s.setdefault("explored_today", [])
    if req.char_id in explored:
        raise HTTPException(400, f"{char['name']}今天已经探索过了！")
    explored.append(req.char_id)
    
    day = s.get("day", 1)
    # 探索概率：随着天数增加，好装备概率略微上升但始终不高
    # 60% 空手而归，25% 获得装备，15% 获得垃圾魔物
    roll = random.random()
    
    if roll < 0.60:
        # 空手
        _log_event(s, "explore", f'{char["name"]} 探索归来——什么也没找到')
        _save(s)
        return {"result": "nothing", "msg": f'{char["name"]}在黑暗中摸索了半天，什么都没发现。'}
    
    elif roll < 0.85:
        # 获得装备 —— 从 exploration 池中选
        pool = [e for e in _equipment_pool if e.get("source") == "exploration"]
        # 后期有小概率出 wave 池装备
        if day > 15 and random.random() < 0.15:
            pool += [e for e in _equipment_by_source.get("wave", []) if e["rarity"] in ("common", "uncommon")]
        if not pool:
            _save(s)
            return {"result": "nothing", "msg": "探索了一番，但地下城能捡的破烂都捡完了。"}
        item = random.choice(pool)
        # 解锁并装备
        unlocked = s.setdefault("unlocked_equipment", [])
        if item["id"] not in unlocked:
            unlocked.append(item["id"])
        char.setdefault("equipment", {"weapon": None, "armor": None, "accessory": None})
        slot = item["slot"]
        old = char["equipment"].get(slot)
        char["equipment"][slot] = item["id"]
        msg = f'{char["name"]}在探索中发现了 {item["name"]}！'
        if old:
            old_item = next((e for e in _equipment_pool if e["id"] == old), None)
            msg += f'（替换了{old_item["name"] if old_item else "旧装备"}）'
        _log_event(s, "explore_equip", msg, {"char": char["name"], "item": item["name"]})
        _save(s)
        return {"result": "equipment", "item": item, "msg": msg}
    
    else:
        # 获得垃圾魔物 —— 从 recruits 池或随机弱属性
        from copy import deepcopy
        if _recruit_pool and random.random() < 0.5:
            mon = random.choice(_recruit_pool)
            species = mon["species"]
            stats = deepcopy(mon["stats"])
            name = mon["name"]
            skills_raw = mon.get("skills_raw", "")
        else:
            weak_species = ["史莱姆", "哥布林", "野狼"]
            sp = random.choice(weak_species)
            species = sp
            name = {"史莱姆": ["绿团", "黏黏"], "哥布林": ["小贼", "尖耳"], "野狼": ["灰崽", "跛脚"]}.get(sp, ["迷路的"])[0]
            stats = {"END": 2, "STR": 2, "SPD": 2, "DEF": 1, "INT": 1, "MP": 1, "WIL": 2}
            skills_raw = ""
        # 构造 CHAR_ADD —— 系统会通过标签加入
        msg = (
            f'[CHAR_ADD: {name} | {species} | '
            + ' '.join(f'{k}:{v}' for k, v in stats.items())
            + (f' | {skills_raw}' if skills_raw else '')
            + ']'
        )
        _log_event(s, "explore_monster", f'{char["name"]} 探索中遇到了 {name}（{species}）', {"char": char["name"], "monster": name, "species": species})
        _save(s)
        return {"result": "monster", "char_add": msg, "name": name, "species": species, "msg": f'{char["name"]}在探索中发现了一只迷路的{species}——{name}！它似乎愿意加入地下城。'}


# ── 事件日志 ──

@app.get("/api/session/{sid}/events")
def list_events(sid: str, limit: int = 50):
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    events = s.get("events", [])
    return {"events": events[-limit:]}

# ── 开发者模式 ──

@app.post("/api/session/{sid}/dev")
def dev_action(sid: str, data: dict):
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    action = data.get("action", "")
    chars = s.get("characters", [])
    active = next((c for c in chars if c["id"] == s.get("active_char_id")), chars[0] if chars else None)

    if not action:
        raise HTTPException(400, "缺少 action 参数")

    if action == "add_exp":
        target_name = data.get("char", active["name"] if active else "")
        amount = data.get("amount", 100)
        for c in chars:
            if c["name"] == target_name:
                c["exp"] = c.get("exp", 0) + amount
                _log_event(s, "exp", f'🔧 [DEV] {c["name"]} 获得 {amount} 经验', {"char": c["name"], "exp": amount, "dev": True})
                # 检查升级
                old_lv = c["level"]
                need_exp = 100 * c["level"]
                while c["exp"] >= need_exp:
                    c["level"] += 1; c["exp"] -= need_exp
                    c["free_points"] += 1
                    c["pending_skill_points"] += 1
                    need_exp = 100 * c["level"]
                if c["level"] > old_lv:
                    _log_event(s, "level_up", f'🔧 [DEV] {c["name"]} 升到 Lv.{c["level"]}', {"char": c["name"], "level": c["level"], "dev": True})
                break
        _save(s); sessions[sid] = s
        return {"ok": True, "characters": chars}

    elif action == "set_level":
        target_name = data.get("char", active["name"] if active else "")
        level = data.get("level", 1)
        for c in chars:
            if c["name"] == target_name:
                old_lv = c["level"]
                c["level"] = max(1, min(99, level))
                c["exp"] = 0
                c["pending_skill_points"] = c["level"]  # 每级1技能点
                _log_event(s, "level_up", f'🔧 [DEV] {c["name"]} 设为 Lv.{c["level"]}', {"char": c["name"], "level": c["level"], "dev": True})
                break
        _save(s); sessions[sid] = s
        return {"ok": True, "characters": chars}

    elif action == "set_day":
        day = data.get("day", 1)
        s["day"] = max(1, day)
        s["days_until_attack"] = data.get("dta", 5)
        s["raid_wave"] = data.get("wave", 1)
        _log_event(s, "system", f'🔧 [DEV] 跳转到第{s["day"]}天 第{s["raid_wave"]}波', {"dev": True})
        _save(s); sessions[sid] = s
        return {"ok": True, "day": s["day"], "days_until_attack": s["days_until_attack"], "raid_wave": s["raid_wave"]}

    elif action == "set_stat":
        target_name = data.get("char", active["name"] if active else "")
        stat = data.get("stat", "")
        value = data.get("value", 3)
        for c in chars:
            if c["name"] == target_name and stat in ATTR_KEYS:
                old = c["stats"].get(stat, 0)
                c["stats"][stat] = max(1, min(99, value))
                _log_event(s, "stat_change", f'🔧 [DEV] {c["name"]} {stat}: {old}→{c["stats"][stat]}', {"char": c["name"], "stat": stat, "old": old, "new": c["stats"][stat], "dev": True})
                break
        _save(s); sessions[sid] = s
        return {"ok": True, "characters": chars}

    else:
        raise HTTPException(400, f"未知操作: {action}")

# ── 骰子 ──

@app.post("/api/roll")
def roll_dice(req: ChatReq):
    msg = req.message.strip()
    m = re.match(r"(\d+)?d(\d+)([+-]\d+)?$", msg, re.IGNORECASE)
    if not m:
        return {"result": f"格式错误：{msg}，正确格式如 3d6+2 或 d20", "detail": ""}

    count = int(m.group(1) or 1)
    sides = int(m.group(2))
    mod = int(m.group(3) or 0)

    if count < 1 or count > 100 or sides < 2 or sides > 1000:
        return {"result": f"骰子参数超限（1-100 个，2-1000 面）", "detail": ""}

    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + mod
    detail = f"{count}d{sides}" + (f"+{mod}" if mod > 0 else f"{mod}" if mod < 0 else "")
    detail += f" = [{', '.join(map(str, rolls))}]"

    if mod != 0:
        detail += f" {'+' if mod > 0 else '-'} {abs(mod)} = {total}"

    return {"result": str(total), "detail": detail}

# ── 会话 ──

@app.get("/api/session/{sid}")
def get_sess(sid: str):
    s = sessions.get(sid) or _load(sid) or new_session()
    return {
        "session_id": s["id"], "title": s["title"],
        "world_setting": s.get("world_setting", DEFAULT_WORLD),
        "characters": s.get("characters", []),
        "active_char_id": s.get("active_char_id", ""),
        "day": s.get("day", 1),
        "days_until_attack": s.get("days_until_attack", 5),
        "raid_wave": s.get("raid_wave", 1),
        "explored_today": s.get("explored_today", []),
        "unlocked_equipment": s.get("unlocked_equipment", []),
        "history": [
            {"role": m["role"], "content": m["content"][:500]}
            for m in s["messages"] if m["role"] in ("user", "assistant")
        ],
    }

class NewSessionReq(BaseModel):
    world_setting: str = ""
    player_name: str = ""
    char_name: str = "小魔王"
    char_species: str = "人类"
    char_coeff: float = 1.3
    char_stats: dict = {}
    char_skills: list = []
    char_passives: list = []

@app.post("/api/session/new")
def create(req: NewSessionReq = None):
    if req is None:
        req = NewSessionReq()
    player = req.player_name or "小魔王"
    s = new_session(
        world_setting=req.world_setting or None,
        player_name=player,
        char_name=req.char_name or req.char_species or "无名魔物",
        char_species=req.char_species or "人类",
        char_coeff=req.char_coeff,
        char_stats=req.char_stats if req.char_stats else None,
        char_skills=req.char_skills if req.char_skills else None,
        char_passives=req.char_passives if req.char_passives else None,
    )
    _save(s)
    return {"session_id": s["id"], "characters": s["characters"], "active_char_id": s["active_char_id"], "world_setting": s["world_setting"], "day": s["day"], "days_until_attack": s["days_until_attack"]}

@app.put("/api/session/{sid}/world")
def upd_world(sid: str, data: dict):
    """更新世界观设定"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    world = data.get("world_setting", DEFAULT_WORLD)
    s["world_setting"] = world
    # 更新第一条系统消息
    sys_content = SYS.replace("{WORLD_SETTING}", world)
    s["messages"][0] = {"role": "system", "content": sys_content}
    _save(s)
    sessions[sid] = s
    return {"world_setting": world}

@app.post("/api/session/{sid}/characters/{cid}/evolve")
def switch_evolve_form(sid: str, cid: str, data: dict):
    """切换进化形态（龙人/巨猫龙）"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    char = next((c for c in s.get("characters", []) if c["id"] == cid), None)
    if not char: raise HTTPException(404)
    if not char.get("evolved"): raise HTTPException(400, "该角色尚未进化")
    form = data.get("form", "")
    if form not in char.get("evolve_forms", []):
        raise HTTPException(400, f"无效形态，可选: {char.get('evolve_forms', [])}")
    old_form = char.get("evolve_form")
    char["evolve_form"] = form
    if form == "龙人形态":
        char["evolve_bonus"] = {"INT": 2, "MP": 2}
    elif form == "巨猫龙形态":
        char["evolve_bonus"] = {"STR": 2, "END": 2}
    _save(s); sessions[sid] = s
    return {"character": char, "switched": old_form != form}

# ── 角色管理 ──

@app.get("/api/session/{sid}/characters")
def list_chars(sid: str):
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    return {"characters": s.get("characters", []), "active_char_id": s.get("active_char_id", "")}

@app.post("/api/session/{sid}/characters")
def add_char(sid: str, req: CharAddReq):
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    c = _make_char(req.name, req.species, req.species_coeff, req.level)
    if req.stats:
        for k in ATTR_KEYS:
            c["stats"][k] = req.stats.get(k, 3)
    s.setdefault("characters", []).append(c)
    _save(s)
    sessions[sid] = s
    return {"character": c}

@app.put("/api/session/{sid}/characters/{cid}")
def upd_char(sid: str, cid: str, data: dict):
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    for c in s.get("characters", []):
        if c["id"] == cid:
            if "stats" in data:
                old_stats = {k: c["stats"].get(k, 0) for k in ATTR_KEYS}
                for k in ATTR_KEYS:
                    if k in data["stats"] and isinstance(data["stats"][k], int) and 0 <= data["stats"][k] <= 99:
                        c["stats"][k] = data["stats"][k]
                changes = [f"{k}:{old_stats.get(k,0)}→{c['stats'][k]}" for k in ATTR_KEYS if old_stats.get(k,0) != c['stats'].get(k,0)]
                _log_event(s, "stat_change", f'{c["name"]} {" ".join(changes) if changes else "属性调整"}', {"char": c["name"], "old": old_stats, "new": dict(c["stats"])})
            if "free_points" in data:
                c["free_points"] = data["free_points"]
            if "pending_skill_points" in data:
                c["pending_skill_points"] = data["pending_skill_points"]
            if "active" in data and data["active"]:
                # 怀孕角色可以设为活跃（允许日常剧情），但会提醒伤害-60%
                s["active_char_id"] = cid
            _save(s)
            sessions[sid] = s
            return {"character": c}
    raise HTTPException(404)

@app.delete("/api/session/{sid}/characters/{cid}")
def del_char(sid: str, cid: str):
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    s["characters"] = [c for c in s.get("characters", []) if c["id"] != cid]
    if s.get("active_char_id") == cid and s["characters"]:
        s["active_char_id"] = s["characters"][0]["id"]
    _save(s)
    sessions[sid] = s
    return {"ok": True}

# ── 装备系统 ──

@app.get("/api/equipment")
def list_equipment(sid: str = ""):
    """返回装备池。标注每件装备当前被哪个角色装备。"""
    if sid:
        s = sessions.get(sid) or _load(sid)
        if s:
            unlocked = s.get("unlocked_equipment", [])
            chars = s.get("characters", [])
            # 收集所有已装备的物品 → 谁装备了它
            equipped_map = {}  # item_id → [char_name, ...]
            for c in chars:
                for slot, eq_id in c.get("equipment", {}).items():
                    if eq_id:
                        equipped_map.setdefault(eq_id, []).append(c["name"])
            result = []
            for e in _equipment_pool:
                if e["id"] in unlocked:
                    item = dict(e)
                    item["equipped_by"] = equipped_map.get(e["id"], [])
                    result.append(item)
            return {"equipment": result, "all_unlocked": unlocked}
    # 无 sid 时仍返回全量
    equipped_map = {}
    result = []
    for e in _equipment_pool:
        item = dict(e)
        item["equipped_by"] = equipped_map.get(e["id"], [])
        result.append(item)
    return {"equipment": result}

@app.put("/api/session/{sid}/characters/{cid}/equip")
def equip_item(sid: str, cid: str, data: dict):
    """给角色装备一件物品。data: {equipment_id: str}"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    item_id = data.get("equipment_id", "")
    item = next((e for e in _equipment_pool if e["id"] == item_id), None)
    if not item:
        raise HTTPException(400, f"装备不存在: {item_id}")
    char = next((c for c in s.get("characters", []) if c["id"] == cid), None)
    if not char:
        raise HTTPException(404, "角色不存在")
    slot = item["slot"]
    char.setdefault("equipment", {"weapon": None, "armor": None, "accessory": None})
    old = char["equipment"].get(slot)
    char["equipment"][slot] = item_id
    _log_event(s, "equip", f'{char["name"]} 装备了 {item["name"]}（{item["type"]}）' + (f'，替换 {old}' if old else ''), {"char": char["name"], "item": item["name"], "slot": slot})
    _save(s); sessions[sid] = s
    return {"ok": True, "equipment": char["equipment"]}

@app.delete("/api/session/{sid}/characters/{cid}/equip/{slot}")
def unequip_item(sid: str, cid: str, slot: str):
    """卸下角色指定槽位的装备"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    char = next((c for c in s.get("characters", []) if c["id"] == cid), None)
    if not char:
        raise HTTPException(404, "角色不存在")
    if slot not in ("weapon", "armor", "accessory"):
        raise HTTPException(400, f"无效槽位: {slot}")
    char.setdefault("equipment", {"weapon": None, "armor": None, "accessory": None})
    old = char["equipment"].get(slot)
    char["equipment"][slot] = None
    if old:
        old_item = next((e for e in _equipment_pool if e["id"] == old), None)
        _log_event(s, "unequip", f'{char["name"]} 卸下了 {old_item["name"] if old_item else old}', {"char": char["name"], "slot": slot})
    _save(s); sessions[sid] = s
    return {"ok": True, "equipment": char["equipment"]}

# ── 工程/陷阱系统 ──

@app.get("/api/constructions")
def list_constructions():
    """返回全部可建造项目（含探索发现的）"""
    return {"constructions": _constructions_pool}

@app.get("/api/session/{sid}/constructions")
def get_constructions(sid: str):
    """查看当前地下城的防御工事"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    return {"constructions": s.get("constructions", [])}

@app.post("/api/session/{sid}/constructions")
def build_construction(sid: str, data: dict):
    """建造防御工事。data: {construction_id: str}"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    con_id = data.get("construction_id", "")
    con = next((c for c in _constructions_pool if c["id"] == con_id), None)
    if not con:
        # 也搜索探索发现的工程
        con = next((c for c in s.get("constructions", []) if c["id"] == con_id), None)
    if not con:
        raise HTTPException(400, f"工程项目不存在: {con_id}")
    existing = s.get("constructions", [])
    same_type = [c for c in existing if c["id"] == con_id]
    if len(same_type) >= con.get("max_count", 99):
        raise HTTPException(400, f"{con['name']}已达建造上限({con['max_count']})")
    build_days = con.get("build_days", 1)
    instance = {
        "instance_id": uuid.uuid4().hex[:6],
        "id": con_id,
        "name": con["name"],
        "type": con["type"],
        "icon": con.get("icon", ""),
        "effect": con.get("effect", {}),
        "status": "building",
        "build_progress": 0,
        "build_total": build_days,
        "started_day": s.get("day", 1),
        "uses_left": con.get("effect", {}).get("uses", 999),
    }
    s.setdefault("constructions", []).append(instance)
    _log_event(s, "build", f'🏗️ 开始建造 {con["name"]}（{con["type"]}）——需{build_days}天', {"construction": con["name"], "day": s.get("day", 1), "build_days": build_days})
    _save(s); sessions[sid] = s
    return {"ok": True, "constructions": s["constructions"]}

@app.delete("/api/session/{sid}/constructions/{iid}")
def demolish_construction(sid: str, iid: str):
    """拆除防御工事"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    old = s.get("constructions", [])
    removed = next((c for c in old if c["instance_id"] == iid), None)
    s["constructions"] = [c for c in old if c["instance_id"] != iid]
    if removed:
        _log_event(s, "demolish", f'🔨 拆除了 {removed["name"]}', {"construction": removed["name"]})
    _save(s); sessions[sid] = s
    return {"ok": True, "constructions": s["constructions"]}

# ── 技能管理 ──

@app.post("/api/session/{sid}/characters/{cid}/skills/generate")
def gen_skills(sid: str, cid: str):
    """为角色生成3个可选技能"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    char = next((c for c in s.get("characters", []) if c["id"] == cid), None)
    if not char: raise HTTPException(404)

    # 1. 优先用 AI 生成
    ai_skills = _ai_gen_skills(char)
    if ai_skills:
        return ai_skills
    
    # 2. AI 失败 → 物种模板保底
    active_skills = _species_skills(char)
    passive = _species_passive(char)
    return {"active": active_skills, "passive": passive}

def _ai_gen_skills(char: dict):
    """调用 LLM 生成技能。失败返回 None"""
    if not os.getenv("OPENAI_API_KEY", ""):
        return None
    
    species = char.get("species", "人类")
    lore = SPECIES_LORE.get(species, {})
    lore_text = json.dumps({
        "物种": species,
        "标签": lore.get("tag",""),
        "战斗风格": lore.get("combat_style",""),
        "技能特色": lore.get("skill_traits",[]),
        "属性倾向": lore.get("base_stats_hint",""),
        "进化路线": lore.get("evolution",[]),
        "背景": (lore.get("lore","") or "")[:200],
    }, ensure_ascii=False)
    
    ctx = (
        f"为以下角色设计2个主动攻击技能+1个格挡技能+1个被动技能。\n\n"
        f"【角色】{char['name']} | 物种:{species} | Lv.{char['level']}\n"
        f"属性: END:{char['stats']['END']} STR:{char['stats']['STR']} SPD:{char['stats']['SPD']} "
        f"DEF:{char['stats']['DEF']} INT:{char['stats']['INT']} MP:{char['stats']['MP']} WIL:{char['stats']['WIL']}\n"
        f"已有技能: {', '.join(s['name'] for s in char.get('skills',[])) or '无'}\n\n"
        f"【物种设定】{lore_text}\n\n"
        f"要求：技能必须符合物种特色和战斗风格，伤害公式参考属性倾向。"
    )
    
    try:
        client = _get_client()
        # 技能生成用 deepseek-chat（v4-pro 返回空）
        m = "deepseek-chat"
        r = client.chat.completions.create(
            model=m,
            messages=[
                {"role": "system", "content": SKILL_GEN_SYS},
                {"role": "user", "content": ctx},
            ],
            temperature=0.95, max_tokens=1000,
        )
        raw = r.choices[0].message.content or ""
        # 提取 JSON
        obj_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not obj_match:
            print(f"[技能AI] 未找到JSON: {raw[:200]}", flush=True)
            return None
        
        data = json.loads(obj_match.group())
        actives = data.get("active", [])
        passive = data.get("passive")
        
        if not actives:
            print(f"[技能AI] active为空: {raw[:200]}", flush=True)
            return None
        
        for sk in actives:
            sk["id"] = _skill_id()
            sk.setdefault("level", 1)
            sk.setdefault("max_level", 10)
            sk.setdefault("category", "主动")
            sk.setdefault("hit_formula", "")
            sk.setdefault("special", None)
        
        if passive:
            passive["id"] = _skill_id()
            passive.setdefault("level", 1)
            passive.setdefault("max_level", 10)
            passive.setdefault("category", "被动")
            passive.setdefault("formula", "")
            passive.setdefault("cost", "")
            passive.setdefault("interval", "")
            passive.setdefault("hit_formula", "")
            passive.setdefault("special", None)
        
        print(f"[技能AI] 成功: {[s['name'] for s in actives]} | {passive.get('name','') if passive else '无'}", flush=True)
        return {"active": actives, "passive": passive}
    
    except Exception as e:
        print(f"[技能AI] 异常: {e}", flush=True)
        return None

# ── 物种技能映射 ──

def _load_species_lore():
    p = BASE / "species_lore.json"
    if p.exists():
        return json.loads(p.read_text("utf-8")).get("species", {})
    return {}

SPECIES_LORE = _load_species_lore()

def _species_skills(char: dict) -> list:
    """根据物种设定生成专属技能"""
    lv = char["level"]
    species = char.get("species", "人类")
    lore = SPECIES_LORE.get(species, {})
    traits = lore.get("skill_traits", ["通用攻击"])
    base = 25 + lv * 8
    
    # 物种 × 技能类型映射
    skill_map = {
        "利爪系":       {"name":"利爪","type":"斩击","formula":f"{base}+2.0×STR+1.5×SPD","hit":"75+2.0×STR+1.0×SPD","cost":f"耐力{16+lv}","interval":"3.0s","desc":"猫科前爪撕裂攻击"},
        "扫尾系":       {"name":"扫尾","type":"钝击","formula":f"{base-5}+1.5×STR+1.0×END","hit":"85+1.5×STR","cost":f"耐力{20+lv}","interval":"4.5s","desc":"龙尾横扫，击退敌人"},
        "龙息系":       {"name":"龙息","type":"法术","formula":f"{base+10}+3.0×INT+1.5×MP","hit":"90","cost":f"蓝{16+lv}","interval":"5.0s","desc":"灼热的龙族吐息"},
        "暗影天赋":     {"name":"暗影突袭","type":"斩击","formula":f"{base}+1.5×SPD+2.0×STR","hit":"70+3.0×SPD","cost":f"耐力{14+lv}","interval":"2.5s","desc":"黑暗掩护下的突袭，先手暴击率+15%"},
        "尾击系":       {"name":"尾击","type":"钝击","formula":f"{base+5}+2.5×STR+0.5×END","hit":"75+2.0×STR","cost":f"耐力{18+lv}","interval":"3.5s","desc":"沉重尾击，击退+眩晕"},
        "飞行系":       {"name":"空袭","type":"斩击","formula":f"{base}+2.0×SPD+1.5×STR","hit":"80+2.5×SPD","cost":f"耐力{20+lv}","interval":"4.0s","desc":"飞行俯冲攻击，无视地形"},
        "鳞甲系":       {"name":"铁壁","type":"防御","formula":"自身DEF+3持续2回合","hit":"","cost":f"耐力{12+lv}","interval":"8.0s","desc":"龙鳞硬化，DEF临时+3"},
        "缠绕系":       {"name":"缠绕","type":"钝击","formula":f"{base-5}+1.5×STR+1.0×SPD","hit":"80+2.0×SPD","cost":f"耐力{14+lv}","interval":"4.0s","desc":"触手缠绕减速，造成DOT"},
        "鞭打系":       {"name":"鞭打","type":"钝击","formula":f"{base}+2.0×STR+0.5×SPD","hit":"75+1.5×STR+1.0×SPD","cost":f"耐力{10+lv}","interval":"2.5s","desc":"多触手鞭打，可攻击多个目标"},
        "墨汁系":       {"name":"墨汁喷射","type":"法术","formula":f"{base-10}+2.0×INT","hit":"70+2.0×INT","cost":f"蓝{12+lv}","interval":"5.0s","desc":"喷射墨汁，致盲敌人(-20命中)"},
        "触手再生":     {"name":"再生","type":"防御","formula":"回复自身HP 15+END×3","hit":"","cost":f"耐力{18+lv}","interval":"12.0s","desc":"触手快速再生，回合末回血"},
        "俯冲系":       {"name":"俯冲","type":"钝击","formula":f"{base+5}+2.0×SPD+1.0×STR","hit":"75+3.0×SPD","cost":f"耐力{16+lv}","interval":"4.0s","desc":"从高处俯冲撞击"},
        "石化系":       {"name":"石化凝视","type":"法术","formula":f"{base-10}+2.0×WIL","hit":"70+2.0×WIL","cost":f"蓝{14+lv}","interval":"6.0s","desc":"石化目光，减速敌人-3SPD"},
        "守护光环":     {"name":"石护","type":"防御","formula":"全员减伤15%持续2回合","hit":"","cost":f"耐力{22+lv}","interval":"10.0s","desc":"展开石翼守护全体队友"},
        "突袭系":       {"name":"致命突袭","type":"刺击","formula":f"{base}+3.5×SPD+0.5×STR","hit":"65+3.5×SPD","cost":f"耐力{8+lv}","interval":"2.0s","desc":"极速突袭，先手必暴"},
        "连咬系":       {"name":"连咬","type":"斩击","formula":f"{base-5}+1.5×SPD+1.0×STR","hit":"75+2.0×SPD","cost":f"耐力{10+lv}","interval":"1.8s","desc":"快速连咬，出血DOT"},
        "闪避系":       {"name":"闪避反击","type":"刺击","formula":f"{base}+2.5×SPD","hit":"80+3.0×SPD","cost":f"耐力{12+lv}","interval":"2.5s","desc":"闪避后反击，额外SPD加成"},
        "撕咬系":       {"name":"撕咬","type":"刺击","formula":f"{base}+2.0×STR+1.5×SPD","hit":"75+1.5×STR+1.0×SPD","cost":f"耐力{10+lv}","interval":"2.5s","desc":"獠牙撕咬，附带出血"},
        "游击系":       {"name":"扑击","type":"钝击","formula":f"{base}+1.5×STR+2.0×SPD","hit":"70+2.0×SPD+1.0×STR","cost":f"耐力{14+lv}","interval":"3.5s","desc":"游击扑击，可位移"},
        "狼群本能":     {"name":"群狼","type":"钝击","formula":f"{base-5}+1.5×STR+1.5×SPD","hit":"75+1.5×SPD+1.0×STR","cost":f"耐力{12+lv}","interval":"3.0s","desc":"与队友协同攻击，同伴越多伤害越高"},
        "嚎叫系":       {"name":"战嚎","type":"防御","formula":"全员伤害+15%持续2回合","hit":"","cost":f"耐力{16+lv}","interval":"8.0s","desc":"狼嚎鼓舞全员增伤"},
        "吞噬系":       {"name":"吞噬","type":"刺击","formula":f"{base-5}+1.5×END+0.5×STR","hit":"70+1.0×END","cost":f"耐力{8+lv}","interval":"3.0s","desc":"吞噬敌人，偷取属性"},
        "变形系":       {"name":"变形","type":"防御","formula":"根据进化改变抗性","hit":"","cost":f"耐力{10+lv}","interval":"6.0s","desc":"临时改变自身伤害抗性"},
        "分裂系":       {"name":"分裂","type":"特殊","formula":"分身攻击50%伤害","hit":"75","cost":f"耐力{20+lv}","interval":"10.0s","desc":"分裂出分身协同攻击"},
        "陷阱系":       {"name":"布设陷阱","type":"特殊","formula":f"{base+5}+2.5×INT","hit":"自动命中","cost":f"耐力{14+lv}","interval":"8.0s","desc":"布置陷阱，下回合自动触发"},
        "投毒系":       {"name":"投毒","type":"法术","formula":f"{base-5}+2.0×INT+1.0×MP","hit":"75+2.0×INT","cost":f"蓝{10+lv}","interval":"4.0s","desc":"投掷毒瓶，DOT+减属性"},
        "佯攻系":       {"name":"佯攻","type":"特殊","formula":"降低敌人命中-20","hit":"80+2.0×INT","cost":f"耐力{8+lv}","interval":"5.0s","desc":"佯攻干扰，敌人命中大减"},
    }
    
    # 从物种的 skill_traits 中选前3个匹配的技能
    skills = []
    for trait in traits:
        # 去掉系别后缀查找
        key = trait.split("（")[0].split("(")[0].strip()
        for skey, tmpl in skill_map.items():
            if skey.startswith(key) or key in skey:
                # 避免重复技能名
                if not any(s["name"] == tmpl["name"] for s in skills):
                    s = dict(tmpl)
                    s["id"] = _skill_id()
                    s["level"] = 1
                    s["max_level"] = 3
                    s["category"] = "主动"
                    skills.append(s)
                    break
        if len(skills) >= 3:
            break
    
    # 不够3个用通用填充
    while len(skills) < 3:
        tmpl = skill_map["利爪系"]
        alt = [
            {"name":"猛击","type":"钝击","formula":f"{base}+2.5×STR+1.0×END","hit":"75+2.0×STR+1.0×SPD","cost":f"耐力{20+lv}","interval":"3.5s","desc":"沉重一击"},
            {"name":"精准刺","type":"刺击","formula":f"{base-5}+2.0×STR+1.5×SPD","hit":"85+2.0×SPD","cost":f"耐力{18+lv}","interval":"2.8s","desc":"瞄准弱点"},
            {"name":"横扫","type":"斩击","formula":f"{base}+1.5×STR+2.0×SPD","hit":"80+1.5×SPD+1.0×STR","cost":f"耐力{22+lv}","interval":"3.0s","desc":"范围攻击"},
        ][len(skills)]
        alt["id"] = _skill_id()
        alt["level"] = 1
        alt["max_level"] = 3
        alt["category"] = "主动"
        skills.append(alt)
    
    return skills

def _species_passive(char: dict) -> dict:
    """根据物种生成专属被动"""
    species = char.get("species", "人类")
    lv = char["level"]
    
    passive_map = {
        "猫龙":   {"name":"黑暗视觉","effect":"黑暗环境不受命中惩罚，命中+10%","desc":"猫科夜视+龙族感知"},
        "幼龙":   {"name":"鳞甲天生","effect":"DEF等效+1，钝伤减伤+10%","desc":"坚硬的龙鳞天生护甲"},
        "触手怪": {"name":"多触须","effect":"每回合额外一次触须攻击(50%伤害)","desc":"多条触手同时作战"},
        "石像鬼": {"name":"石化皮肤","effect":"减伤+8%，受击概率石化攻击者(-3SPD)","desc":"石质皮肤刀枪不入"},
        "杀人兔": {"name":"闪避本能","effect":"闪避率+15%，先手必暴","desc":"极限速度带来超高闪避"},
        "野狼":   {"name":"狼群战术","effect":"场上每多一名同伴，自身伤害+8%","desc":"狼群协作天性"},
        "史莱姆": {"name":"凝胶身体","effect":"钝伤减半，斩击/刺击受伤+25%但可适应进化","desc":"Q弹的身体吸收钝器冲击"},
        "哥布林": {"name":"战术大脑","effect":"每回合额外一次战术行动（陷阱/投毒/佯攻）","desc":"狡诈的头脑在战斗中占尽先机"},
    }
    
    p = passive_map.get(species, {"name":"战斗本能","effect":f"STR+{max(1,lv//3)} SPD+{max(1,lv//3)}","desc":"基础战斗本能"})
    return {
        "id": _skill_id(), "name": p["name"], "type": "被动", "category": "被动",
        "level": 1, "max_level": 10,
        "description": p["desc"],
        "effect": p["effect"],
        "formula": "", "cost": "", "interval": "", "hit_formula": "", "special": None,
    }
@app.post("/api/session/{sid}/characters/{cid}/skills/custom")
def custom_skill(sid: str, cid: str, req: SkillCustomReq):
    """玩家自定义技能——LLM 转成标准格式"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    char = next((c for c in s.get("characters", []) if c["id"] == cid), None)
    if not char: raise HTTPException(404)

    if not os.getenv("OPENAI_API_KEY", ""):
        raise HTTPException(503, "需要 API Key")

    ctx = (
        f"角色：{char['name']} Lv.{char['level']} {char['species']}\n"
        f"属性：END:{char['stats']['END']} STR:{char['stats']['STR']} SPD:{char['stats']['SPD']} "
        f"DEF:{char['stats']['DEF']} INT:{char['stats']['INT']} MP:{char['stats']['MP']} WIL:{char['stats']['WIL']}\n"
        f"玩家描述：{req.description}\n"
        f"请将玩家描述转化为标准技能JSON（name/type/formula/cost/interval/special字段）。"
        f"type选：斩击/刺击/钝击/精神/法术。只输出JSON对象。"
    )

    try:
        client = _get_client()
        m = os.getenv("LLM_MODEL", "deepseek-chat")
        r = client.chat.completions.create(
            model=m, messages=[{"role": "user", "content": ctx}],
            temperature=0.7, max_tokens=400,
        )
        raw = r.choices[0].message.content or "{}"
        obj_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if obj_match:
            skill = json.loads(obj_match.group())
            skill["id"] = _skill_id()
            skill.setdefault("level", 1)
            skill.setdefault("max_level", 10)
            skill.setdefault("description", req.description[:30])
            return {"skill": skill}
    except Exception as e:
        raise HTTPException(500, f"技能生成失败：{e}")

    raise HTTPException(500, "无法解析技能")

@app.post("/api/session/{sid}/characters/{cid}/skills")
def add_skill(sid: str, cid: str, req: SkillAddReq):
    """添加技能到角色（消耗技能点）"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    char = next((c for c in s.get("characters", []) if c["id"] == cid), None)
    if not char: raise HTTPException(404)
    if char["pending_skill_points"] <= 0:
        raise HTTPException(400, "没有可用技能点")

    sk = req.skill
    sk.setdefault("id", _skill_id())
    sk.setdefault("level", 1)
    sk.setdefault("max_level", 10)
    sk["base_cost"] = sk.get("cost", "")  # 存Lv.1原始消耗，后续升级按此缩放
    # 路由：被动→passives[]，主动→skills[]
    if sk.get("category") == "被动":
        char.setdefault("passives", []).append(sk)
    else:
        char["skills"].append(sk)
    char["pending_skill_points"] -= 1
    _save(s)
    sessions[sid] = s
    return {"character": char}

@app.put("/api/session/{sid}/characters/{cid}/skills/{skid}")
def upgrade_skill(sid: str, cid: str, skid: str):
    """升级已有技能（消耗技能点），每级消耗+15%"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    char = next((c for c in s.get("characters", []) if c["id"] == cid), None)
    if not char: raise HTTPException(404)
    if char["pending_skill_points"] <= 0:
        raise HTTPException(400, "没有可用技能点")

    for sk in char["skills"]:
        if sk["id"] == skid:
            if sk["level"] >= sk.get("max_level", 10):
                raise HTTPException(400, "技能已达最高等级")
            sk["level"] += 1
            # 消耗缩放：新消耗 = 基础消耗 × (1 + 0.15 × (等级-1))
            _scale_skill_cost(sk)
            char["pending_skill_points"] -= 1
            _save(s)
            sessions[sid] = s
            return {"character": char}
    # 也查 passives
    for sk in char.get("passives", []):
        if sk["id"] == skid:
            if sk["level"] >= sk.get("max_level", 10):
                raise HTTPException(400, "技能已达最高等级")
            sk["level"] += 1
            _scale_skill_cost(sk)
            char["pending_skill_points"] -= 1
            _save(s)
            sessions[sid] = s
            return {"character": char}
    raise HTTPException(404, "技能不存在")


def _scale_skill_cost(sk):
    """按等级缩放技能消耗：耐力/蓝耗 +15%/级"""
    base = sk.get("base_cost", sk.get("cost", ""))
    if not base or base in ("", "持续", "自动命中"):
        return
    sk["base_cost"] = base  # 确保 base_cost 存在
    lv = sk.get("level", 1)
    scale = 1 + 0.15 * (lv - 1)

    import re
    def _scale_num(m):
        n = float(m.group())
        return f"{n * scale:.1f}".rstrip('0').rstrip('.')

    new_cost = re.sub(r'\d+(\.\d+)?', _scale_num, base)
    sk["cost"] = new_cost

# ── 设置 ──

@app.get("/api/settings")
def settings():
    return {
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
        "model": os.getenv("LLM_MODEL", "deepseek-chat"),
        "has_key": bool(os.getenv("OPENAI_API_KEY", "")),
        "nsfw": os.getenv("NSFW_ENABLED", "") == "true",
    }

@app.put("/api/settings")
def upd_settings(s: SetReq):
    if s.api_key:
        os.environ["OPENAI_API_KEY"] = s.api_key
    if s.base_url:
        os.environ["OPENAI_BASE_URL"] = s.base_url
    if s.model:
        os.environ["LLM_MODEL"] = s.model
    os.environ["NSFW_ENABLED"] = "true" if s.nsfw else "false"
    global _client
    _client = None

    try:
        existing = {}
        env_path = BASE / ".env"
        if env_path.exists():
            for line in env_path.read_text("utf-8").split("\n"):
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()
        existing["OPENAI_API_KEY"] = s.api_key or existing.get("OPENAI_API_KEY", "")
        existing["OPENAI_BASE_URL"] = s.base_url or existing.get("OPENAI_BASE_URL", "https://api.deepseek.com")
        existing["LLM_MODEL"] = s.model or existing.get("LLM_MODEL", "deepseek-chat")
        existing["NSFW_ENABLED"] = "true" if s.nsfw else "false"
        lines = [f"{k}={v}" for k, v in existing.items()]
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass

    return {"ok": True}

# ── 技能模板库 ──

LIBRARY_PATH = BASE / "skill_library.json"

def _load_library() -> dict:
    if LIBRARY_PATH.exists():
        return json.loads(LIBRARY_PATH.read_text("utf-8"))
    return {"templates": [], "design_notes": {}}

def _save_library(data: dict):
    LIBRARY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

STAT_TRANS = {"END":"耐力","STR":"力量","SPD":"速度","DEF":"防御","INT":"智力","MP":"法量","WIL":"意志"}

def _tr(text):
    """翻译文本中的英文属性名为中文"""
    if not text or not isinstance(text, str):
        return text
    for en, zh in STAT_TRANS.items():
        text = text.replace(en, zh)
    return text

@app.get("/api/library")
def get_library():
    lib = _load_library()
    # 从所有会话收集角色 → 去重（同名同物种取最高等级）
    seen = {}  # key: (name, species) → max level entry
    for sid, s in sessions.items():
        for c in s.get("characters", []):
            if c.get("species") == "人类":  # 过滤玩家角色
                continue
            key = (c["name"], c["species"])
            if key in seen and seen[key]["level"] >= c["level"]:
                continue
            seen[key] = {
                "name": c["name"], "species": c["species"],
                "level": c["level"], "stats": c["stats"],
                "skills": [{"name": sk["name"], "type": sk.get("type",""),
                            "formula": _tr(sk.get("formula","")),
                            "hit_formula": _tr(sk.get("hit_formula","")),
                            "cost": sk.get("cost",""),
                            "interval": sk.get("interval",""),
                            "special": _tr(sk.get("special",""))} for sk in c.get("skills",[])],
                "passives": [{"name": p["name"], "effect": _tr(p.get("effect",""))} for p in c.get("passives",[])],
            }
    encountered = sorted(seen.values(), key=lambda x: x["level"], reverse=True)
    # 翻译模板中的公式
    for tpl in lib.get("templates", []):
        for sk in tpl.get("skills", []):
            sk["formula"] = _tr(sk.get("formula", ""))
            sk["hit_formula"] = _tr(sk.get("hit_formula", ""))
    lib["encountered"] = encountered
    lib["encountered_count"] = len(encountered)
    lib["equipment_templates"] = _equipment_templates.get("templates", [])
    return lib

# ── 装备生成 ──

class EquipGenReq(BaseModel):
    rarity: str = "common"
    slot: str = "armor"

@app.post("/api/equipment/generate")
def generate_equipment(req: EquipGenReq):
    """AI 根据稀有度和槽位生成装备"""
    if not os.getenv("OPENAI_API_KEY", ""):
        raise HTTPException(400, "API key 未配置")
    try:
        c = _get_client()
        m = os.getenv("LLM_MODEL", "deepseek-chat")
        guide = json.dumps(_equipment_templates.get("generation_guide", {}), ensure_ascii=False)
        prompt = f"稀有度={req.rarity} 槽位={req.slot}\n生成指南：{guide}"
        msgs = [
            {"role": "system", "content": EQ_GEN_SYS},
            {"role": "user", "content": prompt},
        ]
        r = c.chat.completions.create(model=m, messages=msgs, temperature=0.8, max_tokens=512)
        text = r.choices[0].message.content or "{}"
        # 清理 markdown 包裹
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("\n", 1)[0] if text.endswith("```") else text.split("\n", 1)[1]
        eq = json.loads(text)
        eq["id"] = "eq_gen_" + uuid.uuid4().hex[:8]
        eq["source"] = "generated"
        eq["type"] = {"weapon":"武器","armor":"防具","accessory":"饰品"}.get(eq.get("slot","armor"), "防具")
        # 保存到装备池
        _equipment_pool.append(eq)
        _equipment_by_source.setdefault("generated", []).append(eq)
        return {"ok": True, "equipment": eq}
    except Exception as e:
        raise HTTPException(500, f"装备生成失败: {str(e)[:200]}")

# ── 物种设定 ──

@app.get("/api/species")
def get_species():
    """返回物种详细设定"""
    lore_path = BASE / "species_lore.json"
    if lore_path.exists():
        return json.loads(lore_path.read_text("utf-8"))
    return {"version": "0", "species": {}}

# ── 存档/读档 ──

SAVES_INDEX = BASE / "saves" / "index.json"

def _load_saves_index() -> list:
    if SAVES_INDEX.exists():
        return json.loads(SAVES_INDEX.read_text("utf-8"))
    return []

def _save_saves_index(data: list):
    SAVES_INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

@app.get("/api/saves")
def list_saves():
    """列出所有命名存档"""
    idx = _load_saves_index()
    # 清理已删除的存档引用
    valid = []
    for entry in idx:
        p = BASE / "saves" / entry.get("file", "")
        if p.exists():
            valid.append(entry)
    if len(valid) != len(idx):
        _save_saves_index(valid)
    return {"saves": sorted(valid, key=lambda x: x.get("saved_at", ""), reverse=True)}

@app.post("/api/session/{sid}/save")
def save_session(sid: str, data: dict):
    """命名存档"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404, "会话不存在")
    name = data.get("name", "存档").strip()[:30]
    saved_at = data.get("saved_at", "")
    # 保存到文件
    filename = f"save_{sid}_{name}.json"
    save_path = BASE / "saves" / filename
    # 精简会话数据（去掉大段聊天记录的历史摘要以节省空间）
    slim = {k: v for k, v in s.items()}
    save_path.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
    # 更新索引
    idx = _load_saves_index()
    chars = s.get("characters", [])
    char_summary = ", ".join(f"{c['name']}(Lv.{c['level']})" for c in chars[:3])
    entry = {
        "file": filename, "name": name, "saved_at": saved_at,
        "session_id": sid, "title": s.get("title", "未命名"),
        "characters": char_summary, "msg_count": len(s.get("messages", [])),
    }
    # 替换同名存档
    idx = [e for e in idx if e.get("file") != filename]
    idx.append(entry)
    _save_saves_index(idx)
    return {"ok": True, "entry": entry}

@app.post("/api/saves/{filename}/load")
def load_save(filename: str):
    """加载命名存档到当前会话"""
    save_path = BASE / "saves" / filename
    if not save_path.exists():
        raise HTTPException(404, "存档文件不存在")
    s = json.loads(save_path.read_text("utf-8"))
    sessions[s["id"]] = s
    return {"session_id": s["id"], "title": s.get("title", ""), "characters": s.get("characters", [])}

@app.delete("/api/saves/{filename}")
def delete_save(filename: str):
    """删除存档"""
    save_path = BASE / "saves" / filename
    if save_path.exists():
        save_path.unlink()
    idx = _load_saves_index()
    idx = [e for e in idx if e.get("file") != filename]
    _save_saves_index(idx)
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("WEB_PORT", "8099"))
    uvicorn.run(app, host="127.0.0.1", port=port)
