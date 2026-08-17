# 魔物地下城小酒馆 · 交接文档
> 最后更新：2026-06-27
> 版本：v2.10

---

## 项目概述

Web 文字冒险 RPG。玩家扮演地下城领主，培养魔物、招募同伴、抵御冒险者入侵。德比伦当 GM 毒舌叙述一切。

- **后端**: FastAPI (Python), `server.py` 3225行
- **前端**: 纯 HTML/JS, `index.html` 156KB, 三 Tab（冒险/加点/设置）
- **LLM**: DeepSeek (OpenAI 兼容 API)
- **端口**: 8099

---

## 目录结构

```
derbiren-tavern/
├── server.py              # FastAPI 后端 — 全游戏逻辑
├── consequence_manager.py # 统一概率事件管理（重构完成 ✅）
├── combat/                # 战斗系统独立模块（提取完成 ✅）
│   ├── __init__.py
│   ├── core.py
│   └── skill.py
├── index.html             # 前端
├── recruits.json          # 8 个可招募魔物
├── species_lore.json      # 8 个可选物种设定
├── skill_library.json     # 技能模板库
├── equipment.json         # 装备数据
├── equipment_templates.json
├── constructions.json     # 工事/建筑
├── derbiren_persona.md    # GM 人设
├── plans/                 # 设计文档
│   └── consequence_manager.md
├── reports/               # 审查报告
│   └── analysis_2026-06-12.md  # ⚠️ 已过时
├── tests/
│   └── test_explore_encounter.py  # 探索遇敌回归测试
├── saves/                 # 会话存档 (JSON)
├── venv/                  # Python 虚拟环境
├── .env                   # API Key 等配置
└── README.md
```

---

## 已完成

| 事项 | 状态 |
|------|:--:|
| 基础游戏循环（/day 训练/巡逻/探索/配种/休息/研究/净化） | ✅ |
| 7 属性战斗系统（d100命中 + 无随机伤害 + 护甲穿透） | ✅ |
| 三轮 Raid 系统（Lv3→Lv4群→Lv10三人组） | ✅ |
| 8 物种 + 动态技能生成 + 等级成长 | ✅ |
| 配种系统（跨物种/魔王/杂交亚种/怀孕） | ✅ |
| ConsequenceManager 重构（统一概率管理） | ✅ |
| 战斗系统提取为独立 combat/ 模块 | ✅ |
| 装备系统（掉落/工事建造/品质分级） | ✅ |
| 审查 AI | ✅ 8类标签全覆盖：CHAR_ADD/LEVEL_UP/DMG/EQUIP/CONSTRUCTION/DEATH/BIRTH/EVOLVE |
| 德比伦人设分离（/derbiren 触发） | ✅ |
| 配种/净化/巡逻 startswith bug 修复 | ✅ |
| 上下文管理（消息截断 + 长期记忆摘要） | ✅ |

---

## 待办 / 可迭代方向

| 优先级 | 内容 |
|:--:|------|
| 🔴 | **数值平衡**：命中率靠 SPD 驱动，战士类命中偏低需补偿 |
| 🔴 | **波3难度**：上次测试胜率 5/5，敌人太弱 |
| 🟡 | **探索遇敌兜底**：代码层 50% 概率触发战斗（ConsequenceManager 已有规则） |
| 🟡 | **审查 AI 发现遗漏时通知玩家**（目前只记日志） |
| 🟡 | **起名超时回退**：3天不起名自动用默认名 |
| 🟢 | frontend UI 打磨 |
| 🟢 | 更多物种/技能/装备 |

---

## 启动方式

```bash
cd C:\Users\niutun\AppData\Local\hermes\output\derbiren-tavern
source venv/Scripts/activate
python server.py
# → http://127.0.0.1:8099
```

---

## 测试方式

```bash
# 数值平衡测试
cd C:\Users\niutun\AppData\Local\hermes\output
python combat_test.py

# 探索遇敌回归测试（需 server 运行中）
cd derbiren-tavern
source venv/Scripts/activate
python tests/test_explore_encounter.py
```

---

## AI Agent 操作说明

- 单文件后端，用 `patch` 或 `write_file` 修改 `server.py`
- 改完 `kill` 旧进程 + 重启 `python server.py`
- 状态在 `saves/{session_id}.json`
- 端口 8099 占用检查：`netstat -ano | findstr :8099`
