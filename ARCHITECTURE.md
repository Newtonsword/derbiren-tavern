# Derbiren Tavern — 完整架构与经验手册

> **写给 Hermes Agent 和人类开发者**  
> 这是该项目的唯一权威技术文档。覆盖所有子系统、完整数据流、已知问题及解决方案。  
> 如果你要修改这个项目，先读这份文档。

<!-- AGENT-READABLE HEADER
  repo: github.com/Newtonsword/derbiren-tavern
  entry: server.py (FastAPI, port 8099, ~2800 lines)
  combat: combat/ package (simulator-first, zero AI in battle loop)
  tests: 80 tests in combat/tests/ (pytest, <1s full suite)
  state: saves/{session_id}.json
  frontend: index.html (vanilla JS, ~2600 lines, zero deps)
  python: 3.10+, deps in requirements.txt
  llm: OpenAI-compatible API (default deepseek-chat)
  skill_library: combat/skill_library.json (30KB, 632 lines)
  species: species_lore.json (16KB, 8 species)
  recruits: recruits.json (3KB, 8 unique)
-->

---

## 目录

1. [项目全景](#1-项目全景)
2. [核心架构决策](#2-核心架构决策)
3. [战斗引擎详解](#3-战斗引擎详解)
4. [Buff 系统详解](#4-buff-系统详解)
5. [技能系统](#5-技能系统)
6. [AI 技能选择](#6-ai-技能选择)
7. [装备与经济系统](#7-装备与经济系统)
8. [物种与招募系统](#8-物种与招募系统)
9. [建造系统](#9-建造系统)
10. [配种与进化系统](#10-配种与进化系统)
11. [服务器架构与 API](#11-服务器架构与-api)
12. [前端架构](#12-前端架构)
13. [上下文管理与记忆](#13-上下文管理与记忆)
14. [测试体系](#14-测试体系)
15. [完整踩坑记录](#15-完整踩坑记录)
16. [通用经验教训](#16-通用经验教训)
17. [如何让 LLM 听话使用公式](#17-如何让-llm-听话使用公式)
18. [Hermes Agent 操作手册](#18-hermes-agent-操作手册)

---

## 1. 项目全景

### 1.1 这是什么

**Derbiren Tavern**（小魔王地下城）是一个 AI 驱动的文字冒险 web 游戏。玩家扮演地下城领主（小魔王），培养魔物、建造防御工事、击退冒险者入侵波次。GM 由 **德比伦**（でびるん）——一只黑毛福瑞恶魔——通过 LLM 扮演。

### 1.2 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 后端 | FastAPI + uvicorn | `server.py`，单文件 ~2800 行 |
| 前端 | 原生 JS | `index.html`，零依赖，~2600 行 |
| 战斗 | Python 独立包 | `combat/`，纯程序模拟 |
| AI | OpenAI 兼容 API | 仅叙事+对话，战斗完全不靠 AI |
| 存储 | JSON 文件 | `saves/{session_id}.json` |
| 测试 | pytest | 80 测试，<1s 全量 |
| 运行 | Python 3.10+ | 依赖：fastapi, uvicorn, openai, httpx |

### 1.3 核心理念

- **AI 只管叙事，不管规则** —— 战斗计算 100% 程序化，AI 拿结果润色文字
- **所有效果皆 Buff** —— 中毒/闪避/格挡/属性加成/亡语……统一用 Buff 系统表达
- **单文件可维护** —— 后端单文件，AI 代理可以直接 patch
- **测试即文档** —— 80 个测试覆盖核心行为，看测试比看源码快

### 1.4 项目文件结构

```
derbiren-tavern/
├── server.py                # FastAPI 后端（全部游戏逻辑）
├── index.html               # 单页面前端（原生 JS）
├── species_lore.json        # 8 物种详细设定（16KB）
├── skill_library.json       # 技能模板库（30KB，含设计理由）
├── recruits.json            # 8 个可招募魔物（3KB）
├── derbiren_persona.md      # GM 人格定义
├── README.md                # 项目简介
├── ARCHITECTURE.md          # 本文档
├── requirements.txt         # Python 依赖
├── .env.example             # 环境变量模板
├── saves/                   # JSON 存档（自动创建）
└── combat/                  # 战斗引擎包
    ├── __init__.py          # 公共导出
    ├── sim.py               # 战斗模拟器主循环（CombatSim, 648 行）
    ├── fighter.py           # 战斗单位类（Fighter, ~280 行）
    ├── skill.py             # 技能解析与公式（~180 行）
    ├── buff.py              # Buff 系统（519 行）
    ├── ai.py                # 敌人 AI 技能选择（~200 行）
    ├── position.py          # 站位与距离管理（264 行）
    ├── equipment_scaling.py # 装备效能评分（269 行）
    ├── skill_library.json   # 默认技能库
    └── tests/
        ├── test_sim.py      # 模拟器集成测试（15 个）
        ├── test_fighter.py  # 单位测试（25 个）
        ├── test_skill.py    # 技能测试（30 个）
        └── test_buff.py     # Buff 测试（10 个）
```

---

## 2. 核心架构决策

### 2.1 为什么战斗要从 AI 叙事中剥离

**原始问题**（v2.8 及之前）：
- 战斗由 AI 叙事主导——AI 决定谁打谁、伤害多少、谁赢了
- 同一场战斗在不同 AI 调用中结果不同（随机性不可控）
- 数值设计无法验证（AI 经常忽略公式，或编造不存在的伤害值）
- 格挡/闪避/中毒等机制完全依赖 AI 的「记得与否」

**解决方案**（v2.9+）：
- 将战斗重构为**程序模拟器**
- 0.1 秒 tick 的实时模拟，所有伤害/命中/闪避/Buff 由代码精确计算
- AI 只拿到 `[COMBAT_RESULT]` 日志块，负责润色成叙事文字

```
旧流程:  玩家输入 → AI 叙事（含战斗判定）→ 返回故事
新流程:  玩家输入 → 战斗引擎模拟 → 战斗日志 → AI 润色 → 返回故事
```

### 2.2 为什么用 0.1 秒实时 tick 而非回合制

| 方面 | 回合制 | 实时 tick |
|------|--------|-----------|
| 多单位同时行动 | 需排队 | 自然并行 |
| Buff 持续时间 | 需换算为回合数 | 直接用秒数 |
| 格挡/闪避/反击 | 需额外阶段 | 自然反应 |
| 速度属性 | 决定行动顺序 | 决定行动频率 |
| AI 选技 | 每回合选一次 | 冷却好了就选 |

默认 2000 ticks = 200 秒上限，超过视为超时平局。

### 2.3 为什么所有效果都是 Buff

硬编码特殊效果（如「中毒造成 DoT」「闪避触发反击」）会导致：
- 每加一种效果就要改核心逻辑
- 效果组合爆炸
- 测试覆盖困难

统一用 Buff 系统后：
- 中毒 = `ON_TICK` 触发 + `DEAL_DAMAGE` 原子动作
- 闪避反击 = `ON_DODGE` 触发 + `DEAL_DAMAGE` 原子动作
- 光环 = `ON_COMBAT_START` 触发 + `MODIFY_STAT` 原子动作
- 格挡 = `ON_HIT` 触发 + `BLOCK` 原子动作

### 2.4 为什么是单文件后端

- AI 代理（Hermes）用 `patch` 做精确编辑比跨文件修改安全
- 搜索代码库只需搜一个文件
- 新人（或新 AI）上手不需要理解文件间导入关系

---

## 3. 战斗引擎详解

### 3.1 七属性系统

| 属性 | 缩写 | 职责 | 派生公式 |
|------|------|------|----------|
| 耐力 | END | HP 总量、体力 | HP = END × 100 |
| 力量 | STR | 物理伤害主属性 | — |
| 速度 | SPD | 命中率、闪避、移动速度、技能冷却 | 移动=2.0+SPD×0.3 m/s |
| 防御 | DEF | 护甲减伤、格挡强度 | 减伤% = DEF/(DEF+15) |
| 智力 | INT | 魔法伤害、魔法效果 | — |
| 法量 | MP | 蓝量池 | 蓝量 = MP × 20 |
| 精神 | WIL | 士气、精神抗性 | 精神HP = WIL × 10 |

**设计原则**:
- 属性职责单一：命中只靠 SPD，不混 INT
- 面板直接可算：HP = END×100 一眼就懂
- 没有隐藏数值，所有公式公开

### 3.2 战斗主循环（每 tick）

```
每个 tick = 0.1 秒:

1. 胜负检查 → 一方全灭或超时则结束
2. 位置移动阶段 → 近战追击/远程保持距离
3. 状态推进 → 冷却递减/硬直递减/Buff 倒计时
   ├─ ON_TICK 效果: 再生/DoT/持续恢复
   └─ 体力+0.1/蓝量+0.05 自然恢复
4. 自动防御阶段 → 检测敌方蓄力 → 自动格挡
5. 动作管线 → 前摇/判定/后摇/冷却
6. AI 选技 → 为每个空闲单位选择下一个技能
```

### 3.3 伤害类型

| 类型 | 护甲穿透 | 护甲伤害倍率 | 基础倍率 | 溅射概率 | 溅射比例 |
|------|----------|-------------|---------|----------|---------|
| 刺击 | 10% | 1.5× | 1.08× | 12% | 25% |
| 钝击 | 40% | 1.0× | 0.85× | 30% | 50% |
| 斩击 | 20% | 0.4× | 1.15× | 45% | 35% |
| 法术（火/冰等） | 20% | 0.3× | 1.0× | — | — |
| 精神 | 100%（无视护甲） | 0 | 1.0× | — | — |

### 3.4 伤害管线

```
原始伤害 = (基础值 + Σ(属性 × 系数)) × 被动倍率
    ↓
护甲减伤 = DEF/(DEF+15)  乘法叠加
    实际伤害 = 原始 × (1 - 护甲减伤)
    ↓
格挡 = 50 + 5×DEF  加法叠加
    最终伤害 = max(1, 实际伤害 - 格挡)
    ↓
HP -= 最终伤害 / 护甲 -= 原始×护甲伤害倍率
```

### 3.5 命中判定

```
命中率 = 基础值 + SPD×系数 + 副属性×系数
  - 近战: 50 + SPD×3.0 + STR×0.8
  - 远程: 50 + SPD×3.5 + INT×0.5
  - 魔法: 55 + INT×2.5 + SPD×1.0

判定: d100 ≤ 命中率 → 命中
```

- 远程武器在近战范围（<2m）命中率减半
- 被 stagger 时移动速度减半（0.3s）

### 3.6 近战溅射系统（v2.9.1+）

近战攻击命中时，如果目标周围 3 米内有其他敌人，根据伤害类型概率触发溅射：

- **斩击**: 45% 概率，溅射 35% 伤害 → 宽弧挥砍，最容易刮到旁边的人
- **钝击**: 30% 概率，溅射 50% 伤害 → 震击力道最重，溅射最疼
- **刺击**: 12% 概率，溅射 25% 伤害 → 精准突刺，极少误伤旁边的人

**设计意图**: 防止 BOSS 被杂兵群围殴无还手之力，同时保持三种伤害类型的差异化。

### 3.7 超时处理

- 默认上限 2000 ticks = 200 秒，超时返回 `victor_team = -1`
- 超时不发奖励、不推波次
- AI 叙述中显示选项：「撤退」或「继续打」
- 撤退 → 倒计时重置，波次不变，不给奖励
- 继续打 → 下轮自动重打
- 玩家说别的 → 正常 AI 对话，不卡住

### 3.8 数值调优历史

| 版本 | 问题 | 改动 | 效果 |
|------|------|------|------|
| v2.9 初 | HP=END×200，战斗 40+ 秒 | HP 砍半 = END×100 | — |
| v2.9 初 | 格挡公式 `"0"`，防御废用 | → `50+5×DEF` | 坦克有意义 |
| v2.9 初 | 攻击倍率低 | `15+2.0×STR` → `20+2.5×STR` | 输出 +33% |
| v2.9 终 | 碾压局 12.5s，均势 20.6s | 100 场零超时 | 节奏健康 |
| v2.9.1 | BOSS 1v3 可能输给杂兵 | 近战溅射系统 | 群战平衡 |

---

## 4. Buff 系统详解

### 4.1 核心理念

Buff 是战斗效果的**唯一表达方式**。不写硬编码特殊逻辑。

### 4.2 三层架构

```
TriggerType（触发时机）
  ↓ 当条件满足时
AtomicAction（原子效果）
  ↓ 执行
Buff = 触发条件 + 动作 + 持续时间/层数/概率/条件
```

### 4.3 触发时机（TriggerType）

| 触发器 | 触发条件 | 典型用途 |
|--------|----------|----------|
| `ON_COMBAT_START` | 战斗开始 | 光环/开场 Buff |
| `ON_ATTACK_HIT` | 攻击命中 | 吸血/附加伤害 |
| `ON_ATTACK_MISS` | 攻击未命中 | 惩罚效果 |
| `ON_HIT` | 被攻击命中 | 格挡/反伤 |
| `ON_DODGE` | 闪避成功 | 闪避反击 |
| `ON_KILL` | 击杀敌人 | 击杀回复 |
| `ON_DEATH` | 死亡 | 亡语效果 |
| `ON_TICK` | 每 tick | DoT/HoT |
| `ON_BLOCK` | 格挡成功 | 格挡反击 |
| `ON_STUN` | 被硬直 | 解控效果 |
| `PASSIVE` | 永久 | 属性修正/被动 |

### 4.4 原子动作（AtomicAction）

| 动作 | 说明 | 参数 |
|------|------|------|
| `MODIFY_STAT` | 修改属性 | stat, value |
| `DEAL_DAMAGE` | 造成伤害 | value, condition(衰减模式) |
| `HEAL_HP` | 恢复 HP | value |
| `HEAL_STAMINA` | 恢复体力 | value |
| `HEAL_SPIRIT` | 恢复精神 | value |
| `RESTORE_ARMOR` | 恢复护甲 | value |
| `APPLY_BUFF` | 施加另一个 Buff | buff_def |
| `REMOVE_BUFF` | 移除 Buff | buff_name |
| `STUN` | 硬直 | duration |
| `INTERRUPT` | 打断当前动作 | — |
| `GAIN_ARMOR` | 获得临时护甲 | value |
| `DODGE_NEXT` | 闪避下次攻击 | — |
| `DAMAGE_MULTIPLIER` | 伤害倍率修正 | value（如 0.25=+25%） |
| `BLOCK_MULTIPLIER` | 格挡倍率修正 | value |
| `DR_BY_TYPE` | 按类型减伤 | condition(类型) |
| `HIT_RATE_MOD` | 命中修正 | value |
| `DODGE_RATE_MOD` | 闪避修正 | value |

### 4.5 Buff 实例生命周期

```
施加 Buff → 检查同名 Buff 是否存在
  ├─ 存在 → 叠加层数（不超 max_stacks）→ 刷新持续时间
  └─ 不存在 → 创建新实例
每 tick → 剩余时间递减
  ├─ 到期 → 移除
  └─ 未到期 + 触发条件满足 → 执行动作
```

### 4.6 组合 Buff 示例

「攻击时 30% 概率附加中毒 + 减速」：
```python
# 通过 APPLY_BUFF 原子动作，组合两个简单 Buff
[
    BuffDef(name="中毒", trigger=ON_ATTACK_HIT, chance=0.3,
            action=APPLY_BUFF,
            condition="buff: 剧毒"),  # 引用预设
    BuffDef(name="减速", trigger=ON_ATTACK_HIT, chance=0.3,
            action=APPLY_BUFF,
            condition="buff: 减速"),
]
```

---

## 5. 技能系统

### 5.1 技能定义格式

```json
{
  "name": "猛击",
  "type": "钝击",
  "category": "主动",
  "formula": "30 + 2.5×力量 + 1.0×耐力",
  "hit_formula": "75 + 2.0×速度",
  "cost": "耐力22",
  "interval": "3.5s",
  "ranged": false,
  "effects": {"on_hit": {...}}
}
```

### 5.2 公式解析

`skill.py` 中的 `parse_skill_dict()` 解析技能定义字符串：
- 属性名映射：`力量→STR, 速度→SPD, 耐力→END, 智力→INT, 法量→MP, 精神→WIL`
- 支持中文属性名和英文缩写
- 公式格式：`基础值 + 系数×属性 + 系数×属性`
- 类型归一化：`normalize_type()` 将各种写法映射为 `pierce/slash/blunt/spirit/defense`

### 5.3 技能库（skill_library.json）

30KB 的技能模板库，包含：
- 7 个角色模板（重战士/弓箭手/刺客/法师/盾卫/祭司/召唤师）
- 每个模板 3-4 个主动技能 + 1-2 个被动
- 每个技能带 `rationale` 字段说明设计理由
- 供 AI 生成新技能时参考数值模式

### 5.4 BUFF_PRESETS（预设 Buff）

`skill_library.json` 中预定义了可复用的 Buff 模板：
- 中毒系列：弱毒/剧毒/致命毒（不同 DoT 参数）
- 燃烧/冰冻/麻痹（元素状态）
- 闪避反击/格挡反击
- 击杀回复
- 光环系列：攻击光环/防御光环/速度光环

---

## 6. AI 技能选择

### 6.1 现有实现（ai.py）

`scored_pick_v2()` 函数，使用质量分 + 战场态势调整：

```
每个技能质量分 = 基础分 × 伤害类型修正 × 冷却惩罚
选择: 质量分最高 + 20% 随机扰动（避免死板）
```

战场调整包括：
- 血量 < 30% → 优先防御/回复技能
- 敌方高闪避 → 换高命中技能
- 多敌人在近战范围 → 考虑范围技能

### 6.2 待集成：打分制选择器（ai_scorer.py）

更精细的打分系统已写好但**未集成**：
```
每个技能得分 = 基础分 + 血量修正 + 克制修正 + 位置修正 + 冷却惩罚 + 风险修正
```
集成前需要先在 CombatSim 中切换调用。

---

## 7. 装备与经济系统

### 7.1 装备效能评分

```
power_score = Σ(属性加成) × rarity_mult + skill_bonus + special_bonus
稀有度: common=1, uncommon=1.5, rare=2, epic=3, legendary=4
```

用于自动平衡——不手动给每件装备标价，由公式计算。

### 7.2 奖励分层

**按游戏天数：**

| 天数 | 阶段 | 稀有度上限 | XP 范围 |
|------|------|-----------|---------|
| 1-5 | 入门期 | common | 20-40 |
| 6-10 | 成长期 | uncommon | 40-60 |
| 11-20 | 中期 | rare | 60-100 |
| 21-30 | 后期 | epic | 100-150 |
| 31+ | 大后期 | legendary | 150-250 |

**按波次：**

| 波次 | 稀有度上限 | 装备数量 | XP |
|------|-----------|---------|-----|
| 1 | uncommon | 2 | 40-60 |
| 2 | rare | 2-3 | 60-100 |
| 3 | rare | 3 | 80-120 |
| 4+ | epic | 3 | 100-200 |

### 7.3 装备系统 Bug（缓存污染）

- **问题**: Python 字典引用语义导致多个角色共享 `equipment` 对象
- **症状**: 改 A 的装备，B 也被改了
- **修复**: `copy.deepcopy()` 所有装备字典

---

## 8. 物种与招募系统

### 8.1 8 种可玩物种

| 物种 | 系数 | 定位 | 核心特征 |
|------|------|------|----------|
| 猫龙 | 2.5 | 战斗法师 | INT+STR 双高，暗影主场，可进化 |
| 幼龙 | 2.5 | 重炮型 | 龙息高伤，鳞甲 DEF+1，成长最陡 |
| 触手怪 | 1.8 | 控制型 | 多段攻击，缠绕/致盲/鞭打 |
| 石像鬼 | 1.8 | 飞行坦克 | DEF 最高，可飞行，怕魔法 |
| 杀人兔 | 1.8 | 高速刺客 | SPD 封顶，暴击 15%，身板极脆 |
| 野狼 | 1.3 | 均衡游击 | SPD/STR 均衡，狼群战术 |
| 史莱姆 | 1.0 | 全能进化 | 初始全低，进化路线最多 |
| 哥布林 | 1.0 | 战术型 | 陷阱/毒药/佯攻，正面最弱 |

### 8.2 招募系统

- 巡逻时有 35% 概率触发招募事件
- 8 个独特招募角色（黏黏/吱吱/嘎嘎/硬硬/跳跳/沙沙/滚滚/触触）
- 每个有独立属性、技能和性格描述
- 已招募的不会被重复招募

---

## 9. 建造系统

### 9.1 防御工事

玩家可以建造防御工事来影响战斗：
- 城墙：我方远程命中 +15%，敌方远程 -20%，近战需攀爬
- 各类陷阱：伤害/定身/致盲等效果
- 工事有耐久度和使用次数限制

### 9.2 建造流程

```
/day 建造 名称=xxx 类型=xxx
  → _advance_constructions() 每日推进进度
  → 完工后加入 constructions 列表
  → 战斗时自动计算工事效果
```

---

## 10. 配种与进化系统

### 10.1 配种机制

- 同物种：100% 受孕
- 魔王×魔物：100% 受孕
- 跨物种：根据物种系数差距，30%-80% 不等
- 怀孕天数：1-4 天（根据母方物种系数）
- 怀孕期间：战斗伤害 -60%，无法闪避
- 后代命名：父母名首字拼接 + 「崽」

### 10.2 进化系统

- 猫龙 Lv.10 触发进化选择（龙人形态/巨猫龙形态）
- 其他物种有各自的进化路线（记录在 species_lore.json）
- 进化后获得新技能和属性加成

---

## 11. 服务器架构与 API

### 11.1 启动

```bash
python server.py  # → http://127.0.0.1:8099
```

### 11.2 核心端点

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/session/new` | 创建新游戏 |
| POST | `/api/chat` | **核心**——所有玩家输入入口 |
| GET | `/api/session/{id}` | 完整会话状态 |
| PUT | `/api/session/{id}/world` | 更新世界观 |
| POST | `/api/session/{id}/save` | 手动存档 |
| POST | `/api/saves/{name}/load` | 读档 |
| GET | `/api/session/{id}/characters` | 角色列表 |
| PUT | `/api/session/{id}/characters/{cid}` | 更新角色 |
| DELETE | `/api/session/{id}/characters/{cid}` | 删除角色 |
| POST | `/api/session/{id}/characters/{cid}/skills/generate` | AI 生成技能 |
| POST | `/api/session/{id}/characters/{cid}/skills/custom` | 自定义技能 |
| PUT | `/api/session/{id}/characters/{cid}/skills/{skid}` | 更新技能 |
| PUT | `/api/session/{id}/characters/{cid}/equip` | 装备管理 |
| GET | `/api/session/{id}/constructions` | 建造列表 |
| POST | `/api/session/{id}/constructions` | 新建造 |
| POST | `/api/session/{id}/explore` | 探索奖励 |
| POST | `/api/roll` | 骰子检定 |
| GET | `/api/species` | 物种数据 |
| GET | `/api/library` | 已遭遇角色库 |
| GET | `/api/equipment` | 装备池 |
| GET/PUT | `/api/settings` | 运行时配置 |
| GET | `/api/saves` | 存档列表 |

### 11.3 战斗集成流程（/api/chat 内部）

```
POST /api/chat {message: "/day 锻炼"}

chat() 函数内部:
1. 解析消息 → action = "锻炼"
2. 推进天数 → day+1, days_until_attack-1
3. dta = days_until_attack
4. 日常活动处理（经验/巡逻/配种/建造）
5. 如果 dta == 0:
   a. _run_raid_combat(sess, wave_idx)
      └─ sim.py: CombatSim 运行 → CombatResult
   b. _build_combat_narrative(combat_result)
      └─ 生成人类可读的战斗日志
   c. day_msg 追加 [COMBAT_RESULT]
6. LLM 润色完整 day_msg → clean_reply
7. 胜负处理:
   我方胜: 推进波次 + 发装备/魔物/经验奖励
   敌方胜: 无奖励
   超时(-1): 无奖励，提示撤退/继续
8. 返回 narrative + session 状态
```

### 11.4 会话状态结构

```json
{
  "id": "17f9b6a66b68",
  "title": "小魔王的地下城",
  "day": 10,
  "days_until_attack": 3,
  "raid_wave": 2,
  "characters": [{
    "id": "char_xxx",
    "name": "猫龙",
    "species": "猫龙",
    "level": 8,
    "stats": {"END": 12, "STR": 15, "SPD": 10, ...},
    "skills": [...],
    "equipment": {...},
    "exp": 450,
    "free_points": 2,
    "pending_skill_points": 1
  }],
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "constructions": [{
    "name": "木栅栏",
    "type": "wall",
    "status": "built",
    "effect": {"enemy_ranged_hit": -10},
    "durability": 100
  }],
  "events": [...],
  "_trimmed_summary": "...",
  "_last_combat_victor": 0
}
```

---

## 12. 前端架构

### 12.1 技术选型

- 零依赖原生 JS（不引入框架——降低 AI 理解和修改的门槛）
- CSS 变量控制主题色
- `index.html` 单文件，~2600 行
- 所有 DOM 操作直接 `document.getElementById()` 风格
- 消息渲染：简单的 innerHTML 拼接
- API 调用：`fetch()` with JSON

### 12.2 页面结构

```
#app
├── #topbar（标题栏 + 天数/波次信息）
├── #chat-area（消息滚动区）
│   ├── 系统消息
│   ├── 玩家消息
│   └── GM 消息 (含战斗日志)
├── #input-area（输入框 + 发送按钮）
└── #sidebar（角色面板 / 建造面板 / 设置面板）
```

### 12.3 NSFW 设置

- 隐藏深层菜单（其他设置 → 实验设置）
- 不在表面 UI 暴露
- 激活后影响 system prompt 的色情描写规则

---

## 13. 上下文管理与记忆

### 13.1 上下文截断（_trim_and_summarize）

```
触发条件: messages 超过 MAX_CONTEXT_MESSAGES（默认 80 条）
处理:
  1. 保留最近 20 条消息
  2. 旧消息调用 LLM 生成摘要
  3. 摘要存储为 _trimmed_summary
  4. 注入 system prompt（_inject_summary）
```

### 13.2 摘要注入

```
system prompt = SYS（基础世界观）
              + world_setting（玩家自定义）
              + NSFW 规则
              + _trimmed_summary（历史摘要）
              + day_info（当前天数/倒计时）
              + con_info（防御工事效果）
              + hint（角色面板信息）
```

### 13.3 LLM 配置

```env
OPENAI_API_KEY=sk-xxx           # 必需
OPENAI_BASE_URL=https://api.deepseek.com  # 默认
LLM_MODEL=deepseek-chat         # 默认（v4-pro 不支持 structured output）
LLM_TEMPERATURE=0.85
LLM_MAX_TOKENS=1024
WEB_PORT=8099
SSL_VERIFY=false                # Windows 建议关闭
NSFW_ENABLED=false              # NSFW 模式开关
```

---

## 14. 测试体系

### 14.1 测试结构

```
combat/tests/
├── test_fighter.py   # 25 测试 — Fighter 创建/属性/HP/装备/状态
├── test_skill.py     # 30 测试 — 技能解析/公式/命中/格挡公式
├── test_sim.py       # 15 测试 — 模拟器集成（1v1/2v2/1v3/环境/结果）
└── test_buff.py      # 10 测试 — Buff 施加/触发/叠加/过期/组合
```

### 14.2 运行

```bash
cd derbiren-tavern
python -m pytest combat/ -q      # 简要: 80 passed in 0.3s
python -m pytest combat/ -v      # 详细: 每个测试名称
python -m pytest combat/tests/test_sim.py::TestCombatSim::test_1v1_combat -v
```

### 14.3 测试原则

- 每个测试独立创建 Fighter，不共享状态
- 不用全局单例
- 数值断言用范围而非精确值（受 RNG 影响）
- 战斗胜负用 `in (0, 1)` 而非 `== 0`（万一运气差翻了）
- 属性公式改动 → 先 grep 全局引用 → 更新所有受影响的断言

---

## 15. 完整踩坑记录

### 15.1 `normalize_type` 截断 Bug

**日期**: 2026-06  
**严重程度**: 🔴 致命（技能系统完全瘫痪）

**症状**: 技能解析全失败，所有技能类型无法识别。

**根因**: `parse_skill_dict()` 函数中 `normalize_type` 的 `def` 定义误插入函数体内部（约 line 110），缩进错误导致函数提前 `return`，后续代码未执行。

**修复**:
1. 将 `normalize_type` 移到函数外部
2. 全库搜索 → 发现 6 处遗漏（`sim.py`×3, `ai.py`×2, `position.py`×1）
3. 修复所有遗漏点

**教训**: 
- ⚠️ **一 Bug 即全库扫** —— 修复后立即搜索整个代码库找同类问题
- 嵌套函数定义要小心缩进
- SOUL.md 中已添加规则 #23

### 15.2 格挡公式为 `"0"`

**日期**: 2026-06  
**严重程度**: 🟡 中等（防御技能废用）

**症状**: 所有默认格挡技能无实际减伤。

**根因**: `skill_library.json` 中 6 处格挡技能公式字段为字符串 `"0"`。

**修复**: 改为 `"50 + 5 * DEF"`。

**教训**: 默认值不能是零——零值 Bug 最隐蔽。

### 15.3 装备缓存污染

**日期**: 2026-06  
**严重程度**: 🟡 中等（数据错乱）

**症状**: 给角色 A 换装备，角色 B 的装备也被改变。

**根因**: Python 字典引用语义。`dict.get("equipment", {})` 返回引用，多角色共享同一对象。

**修复**: `copy.deepcopy()` 所有从 JSON 构造的嵌套字典。

**教训**: 从 JSON/字典构造对象时，所有可变字段必须深拷贝。

### 15.4 基准测试 `max_ticks=500` 误判

**日期**: 2026-06  
**严重程度**: 🟡 中等（误导优化方向）

**症状**: 基准测试报告大量「超时」，误以为战斗引擎有性能问题。

**根因**: 测试脚本手动设 `max_ticks=500`（50 秒），而游戏默认 2000 ticks（200 秒）。

**修复**: 测试改用 `max_ticks=2000`，100 场零超时。

**教训**: 测试参数必须和实际游戏参数一致。在测试中硬编码不同上限是自欺欺人。

### 15.5 测试断言写太死

**日期**: 2026-06  
**严重程度**: 🟢 轻微（测试脆断）

**症状**: `test_1v3_combat` 断言 `victor_team == 0`（BOSS 必胜），数值调整后翻车。

**根因**: 3v1 的数量劣势在数值调优后显现，之前 BOSS 赢属于巧合。

**修复**: 改为 `assert victor_team in (0, 1)`。

**教训**: 战斗测试不应断言固定胜负（除非确定性场景）。

### 15.6 HP 公式调整的连锁反应

**日期**: 2026-06  
**严重程度**: 🟡 中等

**问题**: HP 从 `END×200` 砍半为 `END×100`，所有测试的 HP 断言全部失效。

**教训**: 属性公式是系统的重力常数——改动前先 grep 全局引用。

---

## 16. 通用经验教训

### 16.1 开发原则

1. **写代码不如搜代码** —— 修复 Bug 前先搜索全库同类问题
2. **测试即文档** —— 80 个测试覆盖所有核心行为，看测试比看源码快
3. **默认值不能是零** —— 零值 Bug 最难发现
4. **深拷贝一切** —— 从 JSON 构造对象时别省 `copy.deepcopy()`
5. **测试参数必须对齐游戏参数** —— 不要在测试中硬编码不同值
6. **战斗胜负不要写死断言** —— RNG 会让「必胜」断言在将来翻车
7. **单文件后端可维护** —— AI 代理用 `patch` 比跨文件修改安全得多
8. **属性职责单一** —— 命中只靠 SPD，伤害只靠对应属性，不混

### 16.2 战斗设计原则

1. **所有效果皆 Buff** —— 不要在核心循环里硬编码特殊效果
2. **机制优于数值** —— 先让机制正确（格挡真的有减伤），再调数值
3. **三种伤害类型的差异化** —— 不仅数值不同，机制也要不同（溅射概率/比例）
4. **模拟器先跑，眼睛再看** —— 基准测试 100 场，均值方差都有再看

### 16.3 AI 代理特殊注意事项

1. **`server.py` 用 patch 修改，不要 write_file 全量覆盖** —— 2800 行文件全量重写风险极高
2. **改 combat/ 后必须跑 `pytest combat/`** —— 全量测试 <1 秒，不跑就是懒
3. **改 `skill_library.json` 公式 → 同步更新测试断言**
4. **改属性公式 → `grep` 全局引用 → 逐个验证**
5. **战斗 `max_ticks` 默认 2000，不要在测试里乱改**
6. **Python 3.10+ required** —— 类型注解语法 `list[Fighter]` 需要 3.10+

---

## 17. 如何让 LLM 听话使用公式

> **这是整个项目最核心的工程挑战。**  
> LLM 天生爱编造——你不给它枷锁，它就会自己发明伤害数字、忽略公式、凭空创造角色。

### 17.1 问题本质

LLM 在游戏叙事中有三种「不听话」的表现：

| 类型 | 表现 | 危害 |
|------|------|------|
| **编造数值** | AI 说「猫龙造成了 78 点伤害」，但公式算出应该是 45 | 战斗结果不可信 |
| **忽略约束** | AI 凭空描述「一只野狼加入了队伍」但不带标签 | 角色不会出现在面板 |
| **格式偏离** | AI 返回的 JSON 用了英文属性名 `STR` 而非中文 `力量` | 解析失败 |

**根因**: LLM 的本质是「预测下一个 token」，不是「执行程序」。它没有状态、没有计算能力、没有强制约束。你只能**通过提示词引导**它走正确路径。

### 17.2 核心策略：程序算，AI 说

**不要试图让 AI 算数值。** 让程序算完所有数值，AI 只负责把结果翻译成人类可读的叙事。

```
❌ 错误: 把整个战斗逻辑交给 AI
  玩家输入 → AI 判定谁打谁/伤害多少/谁赢 → 返回故事

✅ 正确: 程序算结果，AI 润色
  玩家输入 → 战斗引擎 → 结构化日志 → AI 润色 → 返回故事
```

#### 战斗日志示例（给 AI 的输入）

```
[COMBAT_RESULT]
⚔️ 猫龙 [利爪] 45 → 冒险者 HP-38(格挡7) HP462 护甲0 距离1.2m
⚔️ 冒险者 [挥砍] 22 → 猫龙 HP-15(格挡7) HP485 护甲0 距离1.2m
...
🏆 战斗结束——我方获胜！(12.5秒)

⚠️ 以上是程序生成的战斗日志。请 GM 将其润色为一段精彩的战斗叙事（150-250字），
不需要再计算伤害——所有数值已经由程序判定完毕。
```

**关键**: 最后那句「**不需要再计算伤害——所有数值已经由程序判定完毕**」是咒语。AI 看到这句话会抑制自己编造数值的冲动。

### 17.3 标签系统：结构化数据进出 AI

游戏使用 `[TAG: data]` 格式在 AI 和程序之间传递结构化信息。这是让 AI **输出可解析数据**的最可靠方式。

#### 常用标签一览

| 标签 | 方向 | 用途 |
|------|------|------|
| `[COMBAT_RESULT]` | 程序→AI | 战斗日志块 |
| `[CHAR_ADD: 名 \| 物种 \| 属性 \| 技能]` | AI→程序 | 新角色加入 |
| `[LEVEL_UP: 角色名 \| 新等级]` | AI→程序 | 角色升级 |
| `[BREED]` | 程序→AI | 配种结果 |
| `[BIRTH]` | AI→程序 | 后代出生 |
| `[EVOLVE]` | 程序→AI | 进化事件 |
| `[CONSTRUCTION_DISCOVER]` | 程序→AI | 新工程蓝图 |
| `[DAY_ADVANCE]` | 程序→AI | 推进天数 |
| `[EXP]` | 程序→AI | 经验获得 |

#### 标签解析流程

```
AI 输出 → server.py 正则提取 → 执行对应操作 → 移除标签 → 玩家看到的是干净叙事
```

**关键**: 标签格式必须严格一致。正则表达式不容忍任何偏差。

#### 标签缺失的容错处理

程序会检测「AI 说了有新角色但没带标签」的情况：

```python
# server.py line 982-987
if any(kw in text for kw in ['加入', '新成员', '跟随']) and not has_char_tag:
    warnings.append('💡 系统：检测到新角色描述但未使用 [CHAR_ADD] 标签')
```

这样既不会让面板丢失角色（玩家能看到警告并手动修正），又不会因为 AI 的一次格式失误导致游戏崩溃。

### 17.4 提示词工程：驯服 AI 的具体技巧

#### 技巧 1：禁止比允许更有效

❌ 「请使用正确的伤害公式」  
✅ 「**禁止**自己计算伤害——所有数值已经由程序判定完毕」

LLM 对「禁止」的反应比「请」强烈得多。

#### 技巧 2：给例子，不给原则

❌ 「属性名使用中文」  
✅ 「公式如 `40+2.0×力量+1.5×速度`（**必须使用中文属性名**！**禁止使用 STR/SPD/END 等英文缩写**！）」

告诉 AI 它**可以**这样写，同时告诉它**绝对不能**那样写。

#### 技巧 3：把约束放进 JSON Schema

技能生成的 system prompt 不给「guidelines」而给「JSON schema」：

```json
{
  "formula": "公式如 40+2.0×力量+1.5×速度（必须使用中文属性名！）",
  "hit_formula": "命中公式，如 85+3.0×SPD。未填则用默认",
  "type": "斩击|刺击|钝击|精神|法术|防御"
}
```

AI 看到 JSON 格式会自然输出 JSON，看到枚举值会从中选，看到示例会模仿。

#### 技巧 4：命中公式禁止 STR

```
⚠️ 命中公式禁用STR——STR只影响伤害不影响命中。
```

这是通过经验发现的——AI 经常把 STR 塞进命中公式，导致力量型角色命中率爆炸。

#### 技巧 5：多重保险（fallback chain）

```
技能生成:
  1. AI 生成（temperature=0.95，创意）
  2. AI 失败 → 物种模板保底（硬编码，可靠）
  3. 模板也没有 → 最简默认技能（永不失败）
```

永远不要只有一个路径依赖 AI。AI 会挂、会超时、会返回空内容。Fallback 链是生存必需。

#### 技巧 6：强制数量约束

```
每个角色必须至少有一个近战攻击技能。
如果没有近战技能，系统会自动补一个极弱的应急技。
```

AI 生成的被动/主动技能可能缺失类型。与其相信 AI 不会遗漏，不如在代码里兜底。

#### 技巧 7：用 [标签] 框住 AI 的输出边界

```
⚠️ 你只能使用 [队伍] 中列出的角色。
禁止提到任何不在队伍列表中的名字或物种。
禁止凭空创造魔物同伴——除非系统给了 [CHAR_ADD] 标签。
```

这个三段式约束分别对应：**数据源（只能从哪儿取）→硬禁止（绝对不能做什么）→例外条件（除非系统允许）**。三句话锁死 AI 的「编造角色」冲动。

#### 技巧 8：格式化选项（提供可选择的方向）

```
现在你可以：
- **推开铁门进去**——看看是什么东西还在下层活着
- **先回地面休息**——魔物体力消耗不小，明天再来
- **找找通风口**——先偷瞄一眼里面的情况再做决定
```

AI 给出选项后，前端解析 `- **选项名**——描述` 格式渲染成可点击按钮。这比 AI 自由发挥的「你可以这样做也可以那样做」好控制得多。

### 17.5 技能生成 AI 的完整驯服方案

这是一套经过多轮对抗测试的方案：

**System Prompt（482 行开始）**：
```
你是小魔王地下城世界的技能设计师。
根据角色信息设计 2个主动攻击技能 + 1个格挡技能 + 1个被动技能。

⚠️ 每个角色必须至少有一个近战攻击技能。法师/射手的近战技能应该特别弱。

返回JSON对象（不要其他文字）：
{...具体格式...}

设计原则：
0. ⚠️【强制】所有公式中的属性名必须使用中文。
1. 先判断角色的战斗风格 → 参考属性分配
2. 主动技能公式使用七属性
3. 技能强度与等级匹配（Lv.1-5基伤30-50）
...
10. 闪避技能仅给SPD≥6且DEF≤3的角色
```

**关键设计决策**：
- `temperature=0.95`——创意性任务用高温，但格式约束靠 prompt 的 JSON 模板
- 用 `deepseek-chat` 而非 `deepseek-v4-pro`——v4-pro 在 structured output 任务上返回空
- 返回后正则提取 JSON：`re.search(r'\{.*\}', raw, re.DOTALL)` —— 容忍 AI 在 JSON 前后加废话

### 17.6 NSFW 模式的约束注入

NSFW 模式通过变量替换注入 system prompt：

```python
base_sys = SYS.replace("{NSFW_RULES}", nsfw_rules)
```

NSFW 规则包含大量**负面约束**来控制 AI 的色情描写质量：
- 「禁止 AI 写作腔」——禁用「不是X而是Y」「总而言之」「首先其次最后」
- 「使用直白的福瑞生理词汇」——唧唧/鞘/前液/后穴/肉垫/乳头/精液
- 「句子长短混搭（短句≤30%）」
- 「事后温存收尾，不突然切场景」

同样遵循「禁止+指定替代方案」的模式。

### 17.7 经验总结：让 AI 听话的十条铁律

| # | 铁律 | 反例 |
|---|------|------|
| 1 | **能程序算的不要让 AI 算** | AI 算伤害 → 不可靠 |
| 2 | **禁止比允许更有效** | 「请正确」→ 软弱 |
| 3 | **给 JSON Schema，不给 Guideline** | 「技能要有好数值」→ 模糊 |
| 4 | **永远有 Fallback** | 只靠 AI → 挂了就崩 |
| 5 | **用正则提取，不用相信 AI 格式** | 信 AI 会给你纯 JSON → 它会在前后加废话 |
| 6 | **标签格式必须严格一致** | 今天 `[CHAR_ADD]` 明天 `[CHAR-ADD]` → 正则全挂 |
| 7 | **硬禁止 + 软兜底** | 「禁止忘记近战技能」+ 「忘记了我自动补」 |
| 8 | **属性名统一一种语言** | 混用中文/英文/缩写 → 解析地狱 |
| 9 | **给 AI 提供可选的选项模板** | 自由发挥 → 格式不可控 |
| 10 | **不同任务用不同 temperature 和不同模型** | 创意=high temp+deepseek-chat, 战斗叙事=low temp+deepseek-chat |

### 17.8 本项目的 AI 控制架构全景

```
┌──────────────────────────────────────────────┐
│                   程序层                       │
│  combat/sim.py    → 所有数值计算               │
│  server.py        → 标签解析、正则提取          │
│  combat/buff.py   → 效果判定                   │
└──────────────┬───────────────────────────────┘
               │ 结构化标签 [COMBAT_RESULT]
               │ 结构化标签 [CHAR_ADD: ...]
               ▼
┌──────────────────────────────────────────────┐
│                   AI 层                        │
│  system prompt   → 角色边界、格式约束、禁令     │
│  user prompt     → 具体的结构化数据             │
│  temperature     → 0.85(叙事) / 0.95(创意)     │
│  model 选择      → deepseek-chat (不选 v4-pro) │
└──────────────┬───────────────────────────────┘
               │ AI 输出（含标签）
               ▼
┌──────────────────────────────────────────────┐
│                 解析层                          │
│  regex 提取标签 → 执行游戏逻辑                  │
│  fallback 检查 → 警告/兜底                      │
│  移除标签      → 干净叙事给玩家                  │
└──────────────────────────────────────────────┘
```

---

## 18. Hermes Agent 操作手册

### 18.1 项目路径

```
C:\Users\niutun\derbiren-tavern
```

### 18.2 常用命令

```bash
# 启动服务器
cd C:\Users\niutun\derbiren-tavern && python server.py
# → http://127.0.0.1:8099

# 运行全部测试
python -m pytest combat/ -q

# 单个测试文件
python -m pytest combat/tests/test_sim.py -v

# 查看端口占用
netstat -ano | findstr :8099

# 强制重启
taskkill /F /PID <pid> && python server.py
```

### 18.3 修改代码的安全操作顺序

```
1. read_file 查看目标区域
2. search_files 搜索全局引用
3. patch 做精确编辑
4. pytest combat/ -q 验证
5. 如果有测试挂了 → 分析是测试过时还是改坏了
```

### 18.4 存档管理

```
saves/{session_id}.json    # 游戏存档
测试存档: 17f9b6a66b68     # Day 10, wave 1

手动操作存档的命令在 server.py 的 /api/saves 端点和 /api/session/{id}/save
```

### 18.5 战斗引擎快速调试

```python
# 在 combat/ 目录下直接跑
cd C:\Users\niutun\derbiren-tavern
python -c "
from combat import *
from combat.fighter import make_simple_fighter
from combat.sim import CombatSim, run_sync
t0 = [make_simple_fighter('BOSS', team=0, level=10, STR=15, END=12, SPD=8)]
t1 = [
    make_simple_fighter('杂兵1', team=1, level=2, END=3),
    make_simple_fighter('杂兵2', team=1, level=2, END=3),
    make_simple_fighter('杂兵3', team=1, level=2, END=3),
]
sim = CombatSim(t0, t1, max_ticks=2000)
result = run_sync(sim)
print(f'结果: {"我方赢" if result.victor_team==0 else "敌方赢" if result.victor_team==1 else "超时"}')
print(f'时长: {result.duration}s, ticks: {result.total_ticks}')
"
```

### 18.6 依赖安装

```bash
pip install fastapi uvicorn openai httpx python-dotenv pytest
```

---

## 附录 A: 版本历史

| 版本 | 日期 | 关键变更 |
|------|------|----------|
| v2.8 | 2026-05 | AI 叙事主导战斗 |
| v2.9 | 2026-06-12 | 程序战斗引擎上线、Buff 系统、装备评分、80 测试 |
| v2.9.1 | 2026-06-23 | 近战溅射系统、超时撤退/继续选择、刺击 +8% 基础倍率、溅射 Buff（CLEAVE_RANGE_MOD / CLEAVE_RATIO_MOD + 6 预设） |

## 附录 B: 相关文件索引

| 文件 | 行数 | 用途 |
|------|------|------|
| `server.py` | ~2800 | 全部后端逻辑 |
| `index.html` | ~2600 | 全部前端 UI |
| `combat/sim.py` | 648 | 战斗模拟器主循环 |
| `combat/fighter.py` | ~280 | 战斗单位 |
| `combat/buff.py` | 519 | Buff 系统 |
| `combat/skill.py` | ~180 | 技能解析 |
| `combat/ai.py` | ~200 | AI 技能选择 |
| `combat/position.py` | 264 | 位置/距离/移动 |
| `combat/equipment_scaling.py` | 269 | 装备评分 |
| `combat/skill_library.json` | 632 | 技能模板库 |
| `species_lore.json` | 168 | 物种设定 |
| `recruits.json` | 129 | 可招募魔物 |

---

*最后更新: 2026-06-23*  
*德比伦 & Newt 共同撰写*  
*有任何问题——@Derbiren on QQ*
