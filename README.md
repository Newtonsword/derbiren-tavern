# 🔥 德比伦酒馆 · Derbiren Tavern

德比伦当 GM 的文字冒险 Web 应用。一只黑毛紫尖的雄小鬼福瑞恶魔陪你跑团——毒舌、傲娇、但从不让你真的死掉（大概）。

## 快速开始

**需要 Python 3.10+。**

```bash
# 1. 克隆
git clone https://github.com/Newtonsword/derbiren-tavern.git
cd derbiren-tavern

# 2. 安装依赖
python -m venv venv
source venv/Scripts/activate   # Windows
# source venv/bin/activate     # Linux / Mac
pip install -r requirements.txt

# 3. 配置 API key
cp .env.example .env
# 编辑 .env，填入你的 LLM API key（OpenAI / DeepSeek 兼容格式）

# 4. 启动
python server.py
# 打开 http://127.0.0.1:8099
```

## 功能

| Tab | 说明 |
|-----|------|
| 🗡️ 冒险 | 德比伦 GM 实时叙事，输入行动 → 返回场景 |
| ✨ 加点 | 五属性 STR/AGI/END/INT/WIL + 自由分配点数（默认 10 点） |
| ⚙️ 设置 | 配置 API Key / Base URL / 模型名，保存后即时生效 |

## 配置

所有配置通过 `.env` 文件管理：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `OPENAI_API_KEY` | ✅ | - | LLM API key |
| `OPENAI_BASE_URL` | - | `https://api.deepseek.com` | API 端点 |
| `LLM_MODEL` | - | `deepseek-chat` | 模型名 |
| `LLM_TEMPERATURE` | - | `0.85` | 生成温度（0~2） |
| `LLM_MAX_TOKENS` | - | `1024` | 单次回复最大 token |
| `WEB_PORT` | - | `8099` | Web 服务端口 |
| `SSL_VERIFY` | - | Windows: false, 其他: true | SSL 证书验证 |

## 技术栈

- **后端**: FastAPI + OpenAI 兼容 API（`httpx` 客户端）
- **前端**: 原生 HTML/CSS/JS，零框架依赖
- **存档**: JSON 文件（`saves/` 目录）

## 项目结构

```
├── server.py          # FastAPI 后端
├── index.html         # 三 Tab 前端界面
├── requirements.txt   # Python 依赖
├── .env.example       # 环境变量模板
└── saves/             # 会话存档（自动生成）
```

## License

MIT
