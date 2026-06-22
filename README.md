# 🔥 德比伦酒馆 · Derbiren Tavern v2.9

德比伦当 GM 的文字冒险 Web 应用——一只黑毛紫尖的雄小鬼福瑞恶魔陪你跑团。毒舌、傲娇、护短。

## 快速开始

**需要 Python 3.10+。**

```bash
git clone https://github.com/Newtonsword/derbiren-tavern.git
cd derbiren-tavern
python -m venv venv
source venv/Scripts/activate   # Windows
# 或: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # 填入你的 LLM API key
python server.py               # 打开 http://127.0.0.1:8099
```

> **免费获取 API Key**: [DeepSeek 开放平台](https://platform.deepseek.com/api_keys) — 新用户送 500 万 token

## 功能

| 模块 | 说明 |
|------|------|
| 🗡️ **冒险** | GM 实时叙事，主动掷骰判定、推进剧情、战斗演算 |
| 👥 **角色** | 多角色管理——七属性加点、AI 动态技能生成、等级成长 |
| 🌍 **世界观** | 开新冒险自定义世界观，默认「小魔王地下城」 |
| 🧬 **物种** | 8 物种详细设定（猫龙/幼龙/触手怪/石像鬼/杀人兔/野狼/史莱姆/哥布林），不同系数影响成长 |
| ⚔️ **技能** | 每 3 级 AI 生成全新技能——每物种专属、命中公式独立、被动效果各异 |
| 📅 **天数系统** | 锻炼/巡逻/休息/研究/配种，推进天数备战冒险者入侵 |
| 🎯 **招募** | 巡逻 35% 触发——8 种野生魔物加入队伍，每只有独立性格和技能 |
| 🌊 **Raid 波次** | 预设三波冒险者入侵（Lv.3→Lv.4×5→Lv.10×3），战后自动重置 |
| ⚙️ **设置** | 配置 API Key / Base URL / 模型名，即时生效 |
| 📜 **日志** | 开发者模式 + 事件日志（升级/招募/战斗） |

## 战斗系统 · 小魔王地下城规则

**七属性**: 耐力(END) / 力量(STR) / 速度(SPD) / 防御(DEF) / 法强(INT) / 法量(MP) / 精神(WIL)

**命中判定**: d100 ≤ 最终命中率 → 命中。SPD 是命中主属性，力量型战士命中偏低。
- 近战命中 = 50 + SPD×3.0 + STR×0.8
- 远程命中 = 50 + SPD×3.5 + INT×0.5
- 法术命中 = 55 + INT×2.5 + SPD×1.0

**伤害公式**: `物理伤害 = 基伤 + Σ(属性 × 系数)` — 纯公式无随机骰

**三种伤害类型**: 刺击(穿透45%/削甲×0.4) / 钝击(穿透30%+无视25%) / 斩击(穿透10%/倍率×1.15)

**护甲系统**: 防御(DEF) = 百分比减伤 `DEF/(DEF+15)` | 护甲 = 装备额外 HP 层

**衍生值**: HP=END×200 | 体力=END×50 | 魔法储量=MP×20 | 精神条=WIL×10

**等级**: EXP=300×1.2^(Lv-1) | 每 3 级 1 技能点 | 5 级物种系数

**骰子**: 3d6 + 属性 vs DC | `/r 3d6+STR` 快速掷骰

## 配置

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `OPENAI_API_KEY` | ✅ | - | LLM API key（DeepSeek/OpenAI 兼容） |
| `OPENAI_BASE_URL` | - | `https://api.deepseek.com` | API 端点 |
| `LLM_MODEL` | - | `deepseek-chat` | 模型名 |
| `LLM_TEMPERATURE` | - | `0.85` | 温度 |
| `LLM_MAX_TOKENS` | - | `1024` | 单次最大 token |
| `WEB_PORT` | - | `8099` | 端口 |
| `SSL_VERIFY` | - | Windows: false | SSL 验证 |

## 技术栈

- **后端**: FastAPI + OpenAI 兼容 API（httpx 客户端）
- **前端**: 原生 HTML/CSS/JS，零框架依赖
- **存档**: JSON 文件（`saves/`），兼容旧版自动迁移
- **AI 模型**: 默认 deepseek-chat，支持任意 OpenAI 兼容接口

## 给朋友的话

1. 装 Python 3.10+ → 克隆 → `pip install -r requirements.txt`
2. 去 [platform.deepseek.com](https://platform.deepseek.com/api_keys) 注册拿免费 key
3. 复制 `.env.example` 为 `.env`，把 key 填进去
4. `python server.py` → 浏览器打开 `http://127.0.0.1:8099`
5. 选物种→起名→开玩。输入框里敲 `/day 巡逻` 推进天数，第五天冒险者就来了 🔥

有问题去 GitHub 提 Issue，或者让牛顿转告本大爷 (￣▽￣)

## License

MIT
