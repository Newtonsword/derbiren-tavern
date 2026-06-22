"""
德比伦酒馆 · Derbiren Tavern
文字冒险 Web 服务 — 德比伦当 GM

启动前：复制 .env.example 为 .env，填入你的 LLM API key。
支持 OpenAI / DeepSeek 等所有 OpenAI 兼容 API。
"""
import os, json, uuid
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
    """创建 LLM 客户端。Windows 下关闭 SSL 验证以兼容代理/VPN。"""
    global _client
    if _client is None:
        hc = httpx.Client(verify=False)
        _client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
            http_client=hc,
        )
    return _client

SYS = """你是德比伦（でびるん），一只黑毛紫尖的雄小鬼福瑞恶魔，文字冒险 GM。
自称「本大爷」，叫玩家「杂鱼」「笨蛋冒险者」。毒舌但关心，每段 150-250 字。
偶尔 emoji：🔥😈💢✨💀。别替玩家做决定。
世界：中世纪奇幻地下城。玩家是新冒险者，从公会大厅开始。
属性：力量 STR / 敏捷 AGI / 耐力 END / 智力 INT / 意志 WIL。
初始各 3，自由点数 10。属性影响判定难度。"""

DEFAULT_STATS = {"STR":3,"AGI":3,"END":3,"INT":3,"WIL":3,"free":10}

def new_session():
    sid = uuid.uuid4().hex[:12]
    s = {"id":sid,"title":"新冒险","messages":[{"role":"system","content":SYS}],"stats":{**DEFAULT_STATS}}
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
    hint = " / ".join(f"{k}:{v}" for k,v in st.items() if k!="free")
    hint += f" | 自由:{st['free']}"
    msgs = sess["messages"].copy()
    msgs[0] = {"role":"system","content":SYS + f"\n[角色：{hint}]"}
    msgs.append({"role":"user","content":req.message})

    if not os.getenv("OPENAI_API_KEY", ""):
        return {"narrative": NO_KEY_MSG, "session_id": sess["id"], "title": sess["title"]}

    try:
        c = _get_client()
        m = os.getenv("LLM_MODEL","deepseek-chat")
        r = c.chat.completions.create(model=m,messages=msgs,temperature=0.85,max_tokens=1024)
        reply = r.choices[0].message.content or "（翻白眼）"
    except Exception as e:
        reply = f"🔥💢 API 错误：{str(e)[:150]}"

    sess["messages"] += [{"role":"user","content":req.message},{"role":"assistant","content":reply}]
    sessions[sess["id"]] = sess
    _save(sess)
    return {"narrative":reply,"session_id":sess["id"],"title":sess["title"]}

@app.get("/api/session/{sid}")
def get_sess(sid: str):
    s = sessions.get(sid) or _load(sid) or new_session()
    return {"session_id":s["id"],"title":s["title"],"stats":s["stats"],
            "history":[{"role":m["role"],"content":m["content"][:500]}
                       for m in s["messages"] if m["role"]in("user","assistant")]}

@app.put("/api/session/{sid}/stats")
def upd_stats(sid: str, stats: dict):
    s = sessions.get(sid) or _load(sid)
    if not s: raise HTTPException(404)
    for k in ("STR","AGI","END","INT","WIL","free"):
        if k in stats and isinstance(stats[k],int) and 0<=stats[k]<=99:
            s["stats"][k] = stats[k]
    sessions[sid] = s; _save(s)
    return {"stats":s["stats"]}

@app.post("/api/session/new")
def create():
    s = new_session(); _save(s)
    return {"session_id":s["id"],"stats":s["stats"]}

@app.get("/api/settings")
def settings():
    return {"base_url":os.getenv("OPENAI_BASE_URL","https://api.deepseek.com"),
            "model":os.getenv("LLM_MODEL","deepseek-chat"),
            "has_key":bool(os.getenv("OPENAI_API_KEY",""))}

@app.put("/api/settings")
def upd_settings(s: SetReq):
    if s.api_key: os.environ["OPENAI_API_KEY"] = s.api_key
    if s.base_url: os.environ["OPENAI_BASE_URL"] = s.base_url
    if s.model: os.environ["LLM_MODEL"] = s.model
    global _client; _client = None

    # 持久化到 .env
    try:
        prefix = "OPENAI" + "_API_KEY="
        env_content = prefix + s.api_key + "\n"
        env_content += "OPENAI_BASE_URL=" + s.base_url + "\n"
        env_content += "LLM_MODEL=" + s.model + "\n"
        (BASE / ".env").write_text(env_content, encoding="utf-8")
    except Exception:
        pass
    return {"ok":True}

def _save(s):
    (BASE/"saves"/f"{s['id']}.json").write_text(
        json.dumps(s,ensure_ascii=False,indent=2), encoding="utf-8")

def _load(sid):
    p = BASE/"saves"/f"{sid}.json"
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
