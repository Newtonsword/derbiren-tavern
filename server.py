"""
德比伦酒馆 · Derbiren Tavern
文字冒险 Web 服务 — 德比伦当 GM

启动前：复制 .env.example 为 .env，填入你的 LLM API key。
支持 OpenAI / DeepSeek 等所有 OpenAI 兼容 API。
"""
import os, json, uuid, random, platform
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
    """创建 LLM 客户端。Windows 下默认关闭 SSL 验证（代理/VPN 兼容），
       可通过环境变量 SSL_VERIFY=true 强制开启。"""
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

【骰子规则】
判定格式：`🎲 [属性] 检定 DC=N → 3d6+属性值 = 结果 → (成功/失败)`
- 基础掷 3d6，加对应属性值，对抗 DC
- DC 参考：5=简单 8=普通 11=困难 14=极难 17=传奇

【战斗系统 · 猫科龙地下城规则】
—属性系数（伤害公式核心）—
物理伤害 = 基伤 + Σ(属性 × 系数)
  力量(STR) 系数 2.0 — 近战威力主属性
  速度(SPD) 系数 1.5 — 也影响攻击间隔和闪避
  耐力(END) 系数 0.8 — 撑血+体力+伤害，三合一所以系数低
  法强(INT) 系数 1.2 — 法术伤害 + 精神攻击
基伤 = 30 + 技能等级×10（随技能升级提升）
精神伤害 = 基伤 + 法强 × 技能倍率 × 3

—攻防公式—
命中判定：3d6 + 力量(近战)/速度(远程) vs 敌方闪避 DC
闪避 DC = 10 + 目标速度
护甲减伤率 = 防御(DEF) / (防御 + 15)
  例：DEF=3(轻皮甲)→16.7%，DEF=8(铁甲)→34.8%，DEF=15→50%
实际伤害 = 物理伤害 × (1 - 减伤率)

—三种伤害类型—
刺击：穿透护甲 45%，对护甲伤害高（碎甲快）
钝击：无视护甲 25%，稳定输出
斩击：基础倍率×1.15，对轻甲碾压、对重甲被拉回
每次攻击时根据武器/技能选择类型，描述中体现。

—精神系统—
精神条 = 精神(WIL) × 10
精神伤害直接扣精神条 → 归零 = 丧失战斗力
丧失战斗力判定（HP重伤时触发）：掷 3d6，DC=15-WIL，失败则崩溃
恢复所需回合 = 5 + (10 - WIL)，最少 3 回合

—HP 与体力—
HP = 耐力 × 200
体力 = 耐力 × 50（用于技能消耗）
魔法储量 = 法强 × 20（用于法术消耗）

—攻击间隔—
间隔 = 基础间隔 × (1 - (速度 + 耐力×0.5)/100)
基础间隔：轻攻击 2~3s / 标准 3~4s / 重攻击 4~6s

—等级与经验—
EXP 需求 = 300 × 1.2^(Lv-1)
击败 EXP = 100 × 目标Lv × 物种系数 × 等级差修正
等级差修正：每高 1 级 +15%，每低 1 级 -25%（低 3 级以上归零）
物种系数：杂鱼×1.0 / 普通×1.3 / 精锐×1.8 / 精英×2.5 / Boss×4.0

—环境修正—
狭窄洞穴：长兵间隔×2、远程距离-50%、黑暗命中-25%
宽阔空间：无限制，远程优势恢复

【世界】
中世纪奇幻地下城。玩家从冒险者公会大厅开始。

【角色属性】
耐力 END / 力量 STR / 速度 SPD / 防御 DEF / 法强 INT / 精神 WIL
初始各 3，自由点数 18。
衍生值：HP=END×200，体力=END×50，魔法储量=INT×20，精神条=WIL×10。
属性影响所有相关判定。"""

DEFAULT_STATS = {"END": 3, "STR": 3, "SPD": 3, "DEF": 3, "INT": 3, "WIL": 3, "free": 18}

def new_session():
    sid = uuid.uuid4().hex[:12]
    s = {
        "id": sid, "title": "新冒险",
        "messages": [{"role": "system", "content": SYS}],
        "stats": {**DEFAULT_STATS},
    }
    sessions[sid] = s
    return s

class ChatReq(BaseModel):
    message: str
    session_id: str = ""

class SetReq(BaseModel):
    api_key: str = ""
    base_url: str = ""
    model: str = ""

NO_KEY_MSG = """🔥💢 本大爷没有 API key 用不了！

去 ⚙️设置 页面填你的 LLM API key（DeepSeek/OpenAI 兼容格式即可）。
免费获取 DeepSeek key：https://platform.deepseek.com/api_keys"""

@app.get("/")
def index():
    return FileResponse(BASE / "index.html")

@app.post("/api/chat")
def chat(req: ChatReq):
    sess = sessions.get(req.session_id) or new_session()
    st = sess["stats"]
    hint = " / ".join(f"{k}:{v}" for k, v in st.items() if k != "free")
    hint += f" | 自由:{st['free']}"
    msgs = sess["messages"].copy()
    msgs[0] = {"role": "system", "content": SYS + f"\n[角色：{hint}]"}
    msgs.append({"role": "user", "content": req.message})

    if not os.getenv("OPENAI_API_KEY", ""):
        return {"narrative": NO_KEY_MSG, "session_id": sess["id"], "title": sess["title"]}

    try:
        c = _get_client()
        temp = float(os.getenv("LLM_TEMPERATURE", "0.85"))
        max_tok = int(os.getenv("LLM_MAX_TOKENS", "1024"))
        m = os.getenv("LLM_MODEL", "deepseek-chat")
        r = c.chat.completions.create(model=m, messages=msgs, temperature=temp, max_tokens=max_tok)
        reply = r.choices[0].message.content or "（翻白眼）"
    except Exception as e:
        reply = f"🔥💢 API 错误：{str(e)[:150]}"

    sess["messages"] += [
        {"role": "user", "content": req.message},
        {"role": "assistant", "content": reply},
    ]
    sessions[sess["id"]] = sess
    _save(sess)
    return {"narrative": reply, "session_id": sess["id"], "title": sess["title"]}

# ── 骰子 ──

@app.post("/api/roll")
def roll_dice(req: ChatReq):
    """掷骰：在聊天框输入 /r 2d6+3 或 /r d20 即可。
       也支持 LLM 自动调用此格式。"""
    import re
    msg = req.message.strip()
    # 匹配 NdN+N 格式
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
def get_sess(sid: str):
    s = sessions.get(sid) or _load(sid) or new_session()
    return {
        "session_id": s["id"], "title": s["title"], "stats": s["stats"],
        "history": [
            {"role": m["role"], "content": m["content"][:500]}
            for m in s["messages"] if m["role"] in ("user", "assistant")
        ],
    }

@app.put("/api/session/{sid}/stats")
def upd_stats(sid: str, stats: dict):
    s = sessions.get(sid) or _load(sid)
    if not s:
        raise HTTPException(404)
    for k in ("END", "STR", "SPD", "DEF", "INT", "WIL", "free"):
        if k in stats and isinstance(stats[k], int) and 0 <= stats[k] <= 99:
            s["stats"][k] = stats[k]
    sessions[sid] = s
    _save(s)
    return {"stats": s["stats"]}

@app.post("/api/session/new")
def create():
    s = new_session()
    _save(s)
    return {"session_id": s["id"], "stats": s["stats"]}

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

    # 持久化到 .env（保留用户已有的其他配置）
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
        lines = []
        for k, v in existing.items():
            lines.append(f"{k}={v}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass

    return {"ok": True}

def _save(s):
    (BASE / "saves" / f"{s['id']}.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
    )

def _load(sid):
    p = BASE / "saves" / f"{sid}.json"
    if p.exists():
        try:
            d = json.loads(p.read_text("utf-8"))
            sessions[sid] = d
            return d
        except Exception:
            pass
    return None

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("WEB_PORT", "8099"))
    uvicorn.run(app, host="127.0.0.1", port=port)
