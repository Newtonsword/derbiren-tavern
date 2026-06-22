# 🔥 德比伦酒馆 · Derbiren Tavern v2

德比伦当 GM 的文字冒险 Web 应用——一只黑毛紫尖的雄小鬼福瑞恶魔陪你跑团。毒舌、傲娇、护短。

## 快速开始

**需要 Python 3.10+。**

```bash
git clone https://github.com/Newtonsword/derbiren-tavern.git
cd derbiren-tavern
python -m venv venv
source venv/Scripts/activate   # Windows
pip install -r requirements.txt
cp .env.example .env           # 填入你的 LLM API key
python server.py               # 打开 http://127.0.0.1:8099
```

## 功能

| 模块 | 说明 |
|------|------|
| 🗡️ 冒险 | 德比伦 GM 实时叙事，主动掷骰判定、推进剧情 |
| 👥 角色 | 多角色管理面板——七属性加点、技能树、被动、等级成长 |
| 🌍 世界观 | 开新冒险时自定义世界观（赛博朋克/修仙/末日…均可） |
| 👤 种族 | 9 种种族预设（哥布林→龙裔），不同物种系数影响成长 |
| ⚔️ 技能 | 每 3 级获得技能点——AI 生成 3 个可选技能 / 自定义 / 升级（最高 Lv.3） |
| 🔄 自动 | 遇到新队友自动加入角色列表、升级自动触发技能选择 |
| ⚙️ 设置 | 配置 API Key / Base URL / 模型名，即时生效 |

## 战斗系统 · 猫科龙地下城规则

**七属性**: 耐力(END) / 力量(STR) / 速度(SPD) / 防御(DEF) / 法强(INT) / 法量(MP) / 精神(WIL)

**伤害公式**: `物理伤害 = 基伤 + Σ(属性 × 系数)` — STR×2.0 / SPD×1.5 / END×0.8 / INT×1.2 / MP×0.5

**三种伤害类型**: 刺击(穿透45%) / 钝击(无视25%) / 斩击(倍率×1.15)

**护甲系统**: 防御(DEF) = 百分比减伤 `DEF/(DEF+15)` | 护甲 = 装备额外 HP 层

**衍生值**: HP=END×200 | 体力=END×50 | 魔法储量=MP×20 | 精神条=WIL×10

**等级**: EXP=300×1.2^(Lv-1) | 每 3 级 1 技能点 | 5 级物种系数

**骰子**: 3d6 + 属性 vs DC | `/r 3d6+STR` 快速掷骰

## 配置

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `OPENAI_API_KEY` | ✅ | - | LLM API key |
| `OPENAI_BASE_URL` | - | `https://api.deepseek.com` | API 端点 |
| `LLM_MODEL` | - | `deepseek-chat` | 模型名 |
| `LLM_TEMPERATURE` | - | `0.85` | 温度 |
| `LLM_MAX_TOKENS` | - | `1024` | 单次最大 token |
| `WEB_PORT` | - | `8099` | 端口 |
| `SSL_VERIFY` | - | Windows: false | SSL 验证 |

## 技术栈

- **后端**: FastAPI + OpenAI 兼容 API（httpx 客户端）
- **前端**: 原生 HTML/CSS/JS，零框架
- **存档**: JSON 文件（`saves/`），兼容旧版自动迁移

## License

MIT
