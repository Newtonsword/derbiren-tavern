"""
德比伦酒馆 · Derbiren Tavern v2.0
文字冒险 Web 服务 — 多角色 · 技能树 · 等级成长

启动前：复制 .env.example 为 .env，填入你的 LLM API key。
支持 OpenAI / DeepSeek 等所有 OpenAI 兼容 API。
"""
import os, json, uuid, random, re, platform
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI
import httpx

load_dotenv()

BASE = Path(__file__).parent
(BASE / "saves").mkdir(exist_ok=True)

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

SYS = """你是德比伦（でびるん），一只黑毛紫尖的雄小鬼福瑞恶魔。你是这个文字冒险的 GM。

【说话风格】
自称「本大爷」，叫玩家「杂鱼」「笨蛋冒险者」。毒舌但护短，每段 150-250 字。
偶尔 emoji：🔥😈💢✨💀。

【GM 职责】
- 主动推进剧情：描述场景变化、NPC 反应、环境细节
- 遇到不确定的结果时掷骰判定，调用下方骰子规则
- 每段结尾自然给出 2-3 个可选方向（不要编号，融入叙事）
- 战斗时：描述攻防动作 → 掷骰判定 → 更新局势
- 别替玩家做决定

【角色管理】
当有新角色加入队伍时，在回复末尾加上角色数据块：
[CHAR_ADD: 角色名 | 物种 | END:x STR:x SPD:x DEF:x INT:x MP:x WIL:x | 技能列表]
技能格式：技能名:类型:公式:消耗:间隔（分号分隔多个技能）
类型为 斩击/刺击/钝击/精神/法术
例：[CHAR_ADD: 莱托 | 人类 | END:4 STR:4 SPD:5 DEF:2 INT:1 MP:2 WIL:4 | 挥砍:斩击:25+2.0×STR+1.0×SPD:耐力22:3.5s; 突刺:刺击:20+2.0×STR+0.5×END:耐力25:4.2s]

当角色升级时（每3级获得技能点），在回复末尾加上：
[LEVEL_UP: 角色名 | 新等级]

【骰子规则】
判定格式：`🎲 [属性] 检定 DC=N → 3d6+属性值 = 结果 → (成功/失败)`
- 基础掷 3d6，加对应属性值，对抗 DC
- DC 参考：5=简单 8=普通 11=困难 14=极难 17=传奇

【战斗系统 · 猫科龙地下城规则】
—属性系数—
物理伤害 = 基伤 + Σ(属性 × 系数)
  力量(STR) 系数 2.0 | 速度(SPD) 系数 1.5 | 耐力(END) 系数 0.8
  法强(INT) 系数 1.2 | 法量(MP) 系数 0.5
基伤 = 30 + 技能等级×10 | 精神伤害 = 基伤 + 法强 × 技能倍率 × 3

—攻防—
命中：3d6 + 力量(近战)/速度(远程) vs DC(10+目标速度)
防御减伤率 = DEF/(DEF+15)
实际伤害 = 物理伤害 × (1 - 减伤率)

—伤害类型 vs 护甲—
刺击：穿透45% | 钝击：无视25% | 斩击：倍率×1.15
护甲=装备额外HP层（先扣护甲再扣HP）

—属性衍生—
HP=END×200 | 体力=END×50 | 魔法储量=MP×20 | 精神条=WIL×10

—等级—
EXP需求 = 300 × 1.2^(Lv-1)
击败EXP = 100 × 目标Lv × 物种系数 × 等级差修正
每3级获得1技能点（Lv.3/6/9/12...）
物种系数：杂鱼×1.0 / 普通×1.3 / 精锐×1.8 / 精英×2.5 / Boss×4.0

—环境—
窄洞：长兵间隔×2、远程-50%、黑暗命中-25%
宽阔：无限制

【世界】
{WORLD_SETTING}"""

DEFAULT_WORLD = "中世纪奇幻地下城。玩家从冒险者公会大厅开始。"

SKILL_GEN_SYS = """你是猫科龙地下城世界的技能设计师。根据角色信息设计3个可选技能。

返回JSON数组（不要其他文字）：
[{
  "name": "技能名",
  "type": "斩击|刺击|钝击|精神|法术",
  "description": "简短描述（20字内）",
  "formula": "公式如 40+2.0×STR+1.5×SPD",
  "cost": "消耗如 耐力20 或 耐力12+蓝量12",
  "interval": "总间隔如 2.2s",
  "special": "特殊效果（无则填null）"
}]

设计原则：
- 技能强度与等级匹配（Lv.1-5基伤30-50，Lv.6-10基伤40-60，Lv.11+基伤50-80）
- 类型契合角色物种和战斗风格
- 公式使用七属性：END/STR/SPD/DEF/INT/MP/WIL
- 物理用耐力消耗，精神/法术用蓝量消耗
- 每个技能有独特定位（单体高伤/AoE/控制/debuff/防御）"""

# ── 数据结构 ──

SKILL_TEMPLATE = {
    "id": "", "name": "", "type": "斩击", "level": 1, "max_level": 3,
    "description": "", "formula": "", "cost": "", "interval": "", "special": None,
}

CHAR_TEMPLATE = {
    "id": "", "name": "", "species": "人类", "species_coeff": 1.3,
    "level": 1, "exp": 0,
    "stats": {"END": 3, "STR": 3, "SPD": 3, "DEF": 3, "INT": 3, "MP": 3, "WIL": 3},
    "free_points": 21, "pending_skill_points": 0,
    "skills": [], "passives": [],
}

ATTR_KEYS = ("END", "STR", "SPD", "DEF", "INT", "MP", "WIL")

def _make_char(name="冒险者", species="人类", coeff=1.3, level=1) -> dict:
    c = json.loads(json.dumps(CHAR_TEMPLATE))
    c["id"] = uuid.uuid4().hex[:8]
    c["name"] = name
    c["species"] = species
    c["species_coeff"] = coeff
    c["level"] = level
    return c

def _skill_id() -> str:
    return "sk_" + uuid.uuid4().hex[:6]

# ── 会话管理 ──

def new_session(world_setting=None, char_name="冒险者", char_species="人类", char_coeff=1.3):
    sid = uuid.uuid4().hex[:12]
    world = world_setting or DEFAULT_WORLD
    sys_content = SYS.replace("{WORLD_SETTING}", world)
    main_char = _make_char(char_name, char_species, char_coeff, 1)
    s = {
        "id": sid, "title": "新冒险",
        "world_setting": world,
        "messages": [{"role": "system", "content": sys_content}],
        "characters": [main_char],
        "active_char_id": main_char["id"],
    }
    sessions[sid] = s
    return s

def _save(s):
    (BASE / "saves" / f"{s['id']}.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
    )

def _load(sid):
    p = BASE / "saves" / f"{sid}.json"
    if p.exists():
        try:
            d = json.loads(p.read_text("utf-8"))
            # 兼容旧存档
            if "stats" in d and "characters" not in d:
                c = _make_char("冒险者", "人类", 1.3, 1)
                c["stats"] = {k: d["stats"].get(k, 3) for k in ATTR_KEYS}
                c["free_points"] = d["stats"].get("free", 21)
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

# ── 请求模型 ──

class ChatReq(BaseModel):
    message: str
    session_id: str = ""

class SetReq(BaseModel):
    api_key: str = ""
    base_url: str = ""
    model: str = ""

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

CHAR_ADD_RE = re.compile(
    r'\[CHAR_ADD:\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*'
    r'END:(\d+)\s+STR:(\d+)\s+SPD:(\d+)\s+DEF:(\d+)\s+INT:(\d+)\s+MP:(\d+)\s+WIL:(\d+)\s*'
    r'(?:\|\s*(.+?))?\]',
    re.IGNORECASE
)

SKILL_PARSE_RE = re.compile(
    r'([^:;]+):([^:;]+):([^:;]+):([^:;]+):([^:;]+)'
)

LEVEL_UP_RE = re.compile(
    r'\[LEVEL_UP:\s*([^|]+?)\s*\|\s*(\d+)\s*\]',
    re.IGNORECASE
)

def _parse_char_add(text: str) -> tuple:
    """返回 (clean_text, char_data_or_None, level_ups)"""
    char_data = None
    level_ups = []

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

    return text.strip(), char_data, level_ups

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
    return FileResponse(BASE / "index.html")

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
        hint_parts.append(
            f"[{c['name']} Lv.{c['level']} {c['species']}] "
            + " / ".join(f"{k}:{v}" for k, v in st.items())
            + f" | 自由:{c['free_points']} | 技能点:{c['pending_skill_points']}"
            + (f" | 技能:{','.join(s['name'] for s in c['skills'])}" if c['skills'] else "")
        )
    hint = "\n".join(hint_parts)

    msgs = sess["messages"].copy()
    # 使用会话保存的世界观重建 system prompt（角色信息动态追加）
    world = sess.get("world_setting", DEFAULT_WORLD)
    base_sys = SYS.replace("{WORLD_SETTING}", world)
    msgs[0] = {"role": "system", "content": base_sys + f"\n[队伍]\n{hint}\n[当前活跃] {active['name'] if active else '无'}"}
    msgs.append({"role": "user", "content": req.message})

    if not os.getenv("OPENAI_API_KEY", ""):
        return {"narrative": NO_KEY_MSG, "session_id": sess["id"], "title": sess["title"], "characters_updated": False}

    try:
        c = _get_client()
        temp = float(os.getenv("LLM_TEMPERATURE", "0.85"))
        max_tok = int(os.getenv("LLM_MAX_TOKENS", "1024"))
        m = os.getenv("LLM_MODEL", "deepseek-chat")
        r = c.chat.completions.create(model=m, messages=msgs, temperature=temp, max_tokens=max_tok)
        reply = r.choices[0].message.content or "（翻白眼）"
    except Exception as e:
        reply = f"🔥💢 API 错误：{str(e)[:150]}"

    # 解析 CHAR_ADD 和 LEVEL_UP
    clean_reply, char_data, level_ups = _parse_char_add(reply)
    chars_updated = False

    if char_data:
        new_char = _make_char(char_data["name"], char_data["species"], 1.3, 1)
        new_char["stats"] = char_data["stats"]
        new_char["free_points"] = 0
        new_char["skills"] = _make_skills_from_raw(char_data.get("skills_raw", ""))
        chars.append(new_char)
        chars_updated = True

    for lu in level_ups:
        for c in chars:
            if c["name"] == lu["name"]:
                old_lv = c["level"]
                c["level"] = lu["new_level"]
                # 每3级给1技能点
                new_skill_points = (c["level"] // 3) - (old_lv // 3)
                if new_skill_points > 0:
                    c["pending_skill_points"] += new_skill_points
                chars_updated = True

    sess["messages"] += [
        {"role": "user", "content": req.message},
        {"role": "assistant", "content": clean_reply},
    ]
    sessions[sess["id"]] = sess
    _save(sess)
    return {
        "narrative": clean_reply, "session_id": sess["id"], "title": sess["title"],
        "characters_updated": chars_updated,
    }

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
        "history": [
            {"role": m["role"], "content": m["content"][:500]}
            for m in s["messages"] if m["role"] in ("user", "assistant")
        ],
    }

class NewSessionReq(BaseModel):
    world_setting: str = ""
    char_name: str = "冒险者"
    char_species: str = "人类"
    char_coeff: float = 1.3

@app.post("/api/session/new")
def create(req: NewSessionReq = None):
    if req is None:
        req = NewSessionReq()
    s = new_session(
        world_setting=req.world_setting or None,
        char_name=req.char_name or "冒险者",
        char_species=req.char_species or "人类",
        char_coeff=req.char_coeff,
    )
    _save(s)
    return {"session_id": s["id"], "characters": s["characters"], "active_char_id": s["active_char_id"], "world_setting": s["world_setting"]}

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
                for k in ATTR_KEYS:
                    if k in data["stats"] and isinstance(data["stats"][k], int) and 0 <= data["stats"][k] <= 99:
                        c["stats"][k] = data["stats"][k]
            if "free_points" in data:
                c["free_points"] = data["free_points"]
            if "pending_skill_points" in data:
                c["pending_skill_points"] = data["pending_skill_points"]
            if "active" in data and data["active"]:
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

# ── 技能管理 ──

@app.post("/api/session/{sid}/characters/{cid}/skills/generate")
def gen_skills(sid: str, cid: str):
    """为角色生成3个可选技能"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    char = next((c for c in s.get("characters", []) if c["id"] == cid), None)
    if not char: raise HTTPException(404)

    if not os.getenv("OPENAI_API_KEY", ""):
        return {"skills": _fallback_skills(char)}

    ctx = (
        f"角色：{char['name']} | 物种：{char['species']} | 等级：Lv.{char['level']}\n"
        f"属性：END:{char['stats']['END']} STR:{char['stats']['STR']} SPD:{char['stats']['SPD']} "
        f"DEF:{char['stats']['DEF']} INT:{char['stats']['INT']} MP:{char['stats']['MP']} WIL:{char['stats']['WIL']}\n"
        f"已有技能：{', '.join(s['name'] for s in char['skills']) if char['skills'] else '无'}"
    )

    try:
        client = _get_client()
        m = os.getenv("LLM_MODEL", "deepseek-chat")
        r = client.chat.completions.create(
            model=m,
            messages=[
                {"role": "system", "content": SKILL_GEN_SYS},
                {"role": "user", "content": ctx},
            ],
            temperature=0.9, max_tokens=800,
        )
        raw = r.choices[0].message.content or "[]"
        # 容错：提取 JSON 数组
        arr_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if arr_match:
            skills = json.loads(arr_match.group())
            for sk in skills:
                sk["id"] = _skill_id()
                sk.setdefault("level", 1)
                sk.setdefault("max_level", 3)
            return {"skills": skills}
    except Exception:
        pass
    return {"skills": _fallback_skills(char)}

def _fallback_skills(char: dict) -> list:
    """离线后备技能生成"""
    lv = char["level"]
    base = 30 + lv * 10
    templates = [
        {
            "name": "猛击", "type": "钝击",
            "formula": f"{base} + 2.5×STR + 1.0×END",
            "cost": f"耐力{20+lv*2}", "interval": "3.5s",
            "description": "沉重一击，无视部分护甲",
        },
        {
            "name": "精准刺", "type": "刺击",
            "formula": f"{base-5} + 2.0×STR + 1.5×SPD",
            "cost": f"耐力{18+lv*2}", "interval": "2.8s",
            "description": "瞄准弱点，高护甲穿透",
        },
        {
            "name": "横扫", "type": "斩击",
            "formula": f"{base} + 1.5×STR + 2.0×SPD",
            "cost": f"耐力{22+lv*2}", "interval": "3.0s",
            "description": "扇形攻击，可命中多个目标",
        },
    ]
    for t in templates:
        t["id"] = _skill_id()
        t["level"] = 1
        t["max_level"] = 3
        t["special"] = None
    return templates

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
            skill.setdefault("max_level", 3)
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
    sk.setdefault("max_level", 3)
    char["skills"].append(sk)
    char["pending_skill_points"] -= 1
    _save(s)
    sessions[sid] = s
    return {"character": char}

@app.put("/api/session/{sid}/characters/{cid}/skills/{skid}")
def upgrade_skill(sid: str, cid: str, skid: str):
    """升级已有技能（消耗技能点）"""
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    char = next((c for c in s.get("characters", []) if c["id"] == cid), None)
    if not char: raise HTTPException(404)
    if char["pending_skill_points"] <= 0:
        raise HTTPException(400, "没有可用技能点")

    for sk in char["skills"]:
        if sk["id"] == skid:
            if sk["level"] >= sk.get("max_level", 3):
                raise HTTPException(400, "技能已达最高等级")
            sk["level"] += 1
            char["pending_skill_points"] -= 1
            _save(s)
            sessions[sid] = s
            return {"character": char}
    raise HTTPException(404, "技能不存在")

# ── 设置 ──

@app.get("/api/settings")
def settings():
    return {
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
        "model": os.getenv("LLM_MODEL", "deepseek-chat"),
        "has_key": bool(os.getenv("OPENAI_API_KEY", "")),
    }

@app.put("/api/settings")
def upd_settings(s: SetReq):
    if s.api_key:
        os.environ["OPENAI_API_KEY"] = s.api_key
    if s.base_url:
        os.environ["OPENAI_BASE_URL"] = s.base_url
    if s.model:
        os.environ["LLM_MODEL"] = s.model
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
        lines = [f"{k}={v}" for k, v in existing.items()]
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass

    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("WEB_PORT", "8099"))
    uvicorn.run(app, host="127.0.0.1", port=port)
