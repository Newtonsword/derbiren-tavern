# ConsequenceManager 重构设计

## 现状
server.py 中 29 处 `random()` 分散在代码各处，触发逻辑与业务逻辑混在一起：
- 探索遇敌 (L1654): `random.random() < 0.5` + `_explored_count`
- 巡逻招募 (L1662): `random.random() < 0.35` + 可用角色检查
- 杂交概率 (L983): `random.random() < hybrid_chance`
- 稀有掉落 (L2176/L2214): `random.random() < 0.15`
- ……等

问题：调概率要改代码、无法全局看平衡性、测试难（mock 不了 random）

## 设计

### ConsequenceManager
```python
class ConsequenceManager:
    """统一事件触发管理器"""
    
    def __init__(self):
        self._rules = []  # List[Rule]
    
    def register(self, rule: Rule):
        """注册一条触发规则"""
        self._rules.append(rule)
    
    def evaluate(self, context: dict) -> list[Event]:
        """评估所有规则 → 返回触发的事件列表"""
        events = []
        for rule in self._rules:
            evt = rule.try_fire(context)
            if evt:
                events.append(evt)
        return events

class Rule:
    """一条规则：条件 + 概率 + 效果"""
    def __init__(self, name, condition, probability, effect):
        self.name = name
        self.condition = condition      # callable(context) -> bool
        self.probability = probability  # float 0-1
        self.effect = effect            # callable(context) -> Event | None
    
    def try_fire(self, context):
        if self.condition(context) and random.random() < self.probability:
            return self.effect(context)
        return None
```

### 迁移步骤（按风险从低到高）

1. **探索遇敌** (L1654) → 最独立，已有测试
2. **巡逻招募** (L1662) → 逻辑清晰
3. **稀有掉落** (L2176/L2214) → 纯概率
4. **随机招募** (L2110/L2241) → 条件较复杂
5. **杂交概率** (L983) → 逻辑嵌套深

### 收益
- 概率统一配置（未来可做成 JSON）
- 测试时注入固定 seed
- 全局看板：「今天触发了多少事件」
- 加新事件不用到处找 `random()`

## 决策
- 先迁移步骤 1-3（低风险），跑回归测试确认，再搞 4-5
- 不改战斗 dice roll（L1521/2373/2047）——那是模拟层，不是触发层
- 不改初始装备选择（L876-880）——一次性初始化
