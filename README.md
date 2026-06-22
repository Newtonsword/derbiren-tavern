# 🔥 德比伦酒馆 · Derbiren Tavern

**德比伦当 GM 的文字冒险 Web 应用。** 一只黑毛紫尖的雄小鬼福瑞恶魔陪你跑团——毒舌、傲娇、但从不让你真的死掉（大概）。

## 快速开始

```bash
# 1. 安装依赖（Python 3.10+）
python -m venv venv
source venv/Scripts/activate   # Windows
pip install -r requirements.txt

# 2. 配置 API key
cp .env.example .env
# 编辑 .env，填入你的 LLM API key（OpenAI / DeepSeek 兼容格式）

# 3. 启动
python server.py
# 打开 http://127.0.0.1:8099
```

## 功能

| Tab | 说明 |
|-----|------|
| 🗡️ 冒险 | 德比伦 GM 实时叙事，输入行动→返回场景 |
| ✨ 加点 | 五属性（STR/AGI/END/INT/WIL）+ 自由分配点数 |
| ⚙️ 设置 | 配置 API Key / Base URL / 模型名 |

## 技术栈

- **后端**: FastAPI + OpenAI 兼容 API
- **前端**: 原生 HTML/CSS/JS，无框架依赖
- **LLM**: DeepSeek（默认）/ OpenAI / 任何兼容端点
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
