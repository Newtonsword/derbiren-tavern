"""
ConsequenceManager — 统一事件触发管理器
替代 server.py 中散落的 random() 硬编码
"""
import random
from dataclasses import dataclass, field
from typing import Callable, Any, Optional


@dataclass
class Event:
    """触发的事件"""
    name: str
    data: dict = field(default_factory=dict)


class ConsequenceManager:
    """集中管理所有概率触发事件"""

    def __init__(self, seed: Optional[int] = None):
        self._rules: list["Rule"] = []
        self._rng = random.Random(seed) if seed is not None else random

    def register(self, rule: "Rule") -> None:
        self._rules.append(rule)

    def evaluate(self, context: dict) -> list[Event]:
        """评估所有规则，返回触发的事件列表"""
        events = []
        for rule in self._rules:
            evt = rule.try_fire(context, self._rng)
            if evt is not None:
                events.append(evt)
        return events

    @property
    def rule_count(self) -> int:
        return len(self._rules)


class Rule:
    """一条触发规则：条件 → 概率 → 效果"""

    def __init__(
        self,
        name: str,
        condition: Callable[[dict], bool],
        probability: float,
        effect: Callable[[dict, random.Random], Optional[Event]],
        description: str = "",
    ):
        self.name = name
        self.condition = condition
        self.probability = probability
        self.effect = effect
        self.description = description

    def try_fire(self, context: dict, rng: random.Random) -> Optional[Event]:
        if not self.condition(context):
            return None
        if rng.random() >= self.probability:
            return None
        return self.effect(context, rng)


# ============================================================
# 预制规则工厂（对应 server.py 中的场景）
# ============================================================

def explore_encounter_rule() -> Rule:
    """探索遇敌：50% 概率遭遇随机敌人"""
    ENCOUNTER_POOL = [
        {"name": "暗影蝙蝠", "desc": "黑暗中扑出一只暗影蝙蝠，发出尖锐的嘶叫！"},
        {"name": "岩石傀儡", "desc": "地道深处传来沉重的脚步声——一尊岩石傀儡挡住了去路！"},
        {"name": "毒雾巨鼠", "desc": "一股恶臭袭来，三只毒雾巨鼠从裂缝中窜出！"},
        {"name": "幽灵斥候", "desc": "半透明的幽灵斥候在空气中凝聚成形，发出低沉的警告声。"},
        {"name": "骷髅战士", "desc": "墙壁后推开一具骷髅战士，骨刀在黑暗中闪着寒光。"},
        {"name": "藤蔓触手", "desc": "天花板上垂下数根藤蔓触手，卷向你的脚踝！"},
        {"name": "地穴潜伏者", "desc": "脚下地面突然塌陷——一只地穴潜伏者从坑中跃出！"},
    ]

    def condition(ctx):
        return '探索' in ctx.get('action', '') and ctx.get("_explored_count", 0) <= 1

    def effect(ctx, rng):
        enc = rng.choice(ENCOUNTER_POOL)
        return Event(
            name="explore_encounter",
            data={"enemy": enc["name"], "intro": enc["desc"]},
        )

    return Rule(
        name="探索遇敌",
        condition=condition,
        probability=0.5,
        effect=effect,
        description="探索时 50% 遭遇随机敌人",
    )


def patrol_recruit_rule() -> Rule:
    """巡逻招募：35% 概率遇到可招募魔物"""
    def condition(ctx):
        return '巡逻' in ctx.get('action', '') and bool(ctx.get("available_recruits"))

    def effect(ctx, rng):
        available = ctx["available_recruits"]
        mon = rng.choice(available)
        return Event(
            name="patrol_recruit",
            data={"monster": mon, "species": mon.get("species", "未知")},
        )

    return Rule(
        name="巡逻招募",
        condition=condition,
        probability=0.35,
        effect=effect,
        description="巡逻时 35% 遇到可招募魔物",
    )


# ============================================================
# 使用示例
# ============================================================
if __name__ == "__main__":
    mgr = ConsequenceManager(seed=42)
    mgr.register(explore_encounter_rule())
    mgr.register(patrol_recruit_rule())

    # 模拟探索
    ctx = {"action_type": "探索", "_explored_count": 0}
    for i in range(10):
        events = mgr.evaluate(ctx)
        print(f"探索{i+1}: {[e.name for e in events]}")
