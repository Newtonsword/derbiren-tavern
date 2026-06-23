"""
Buff 系统 —— 所有效果皆 Buff，复杂 Buff 由简单 Buff 组合

参考 Unity 卡牌游戏架构:
  TriggerType  → 触发时机
  AtomicAction → 原子效果
  Buff = 触发条件 + 动作链 + 持续/层数

设计原则:
  - 简单 buff: 单个 AtomicAction (如 "力量+5")
  - 复杂 buff: 多个简单 buff 组合 (如 "攻击时 30% 概率附加中毒+减速")
  - 所有效果通过 BuffManager 统一管理，避免硬编码特殊效果
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional, Any

class TriggerType(Enum):
    """触发时机 —— buff 在什么时候生效"""
    ON_ATTACK_HIT = auto()       # 攻击命中时
    ON_ATTACK_MISS = auto()      # 攻击未命中时
    ON_HIT = auto()              # 被攻击命中时
    ON_DODGE = auto()            # 闪避成功时
    ON_KILL = auto()             # 击杀时
    ON_DEATH = auto()            # 死亡时
    ON_TICK = auto()             # 每 tick (持续性效果)
    ON_COMBAT_START = auto()     # 战斗开始时
    ON_COMBAT_END = auto()       # 战斗结束时
    ON_LOW_HP = auto()           # HP 低于阈值时
    ON_BLOCK = auto()            # 格挡时
    ON_STUN = auto()             # 被硬直时
    PASSIVE = auto()             # 永久被动 (属性修正)

class AtomicAction(Enum):
    """原子效果 —— 不可再分的战斗效果单元"""
    MODIFY_STAT = auto()         # 修改属性 (STR/SPD/DEF/...)
    DEAL_DAMAGE = auto()         # 造成伤害
    HEAL_HP = auto()             # 恢复 HP
    HEAL_STAMINA = auto()        # 恢复体力
    HEAL_SPIRIT = auto()         # 恢复精神
    RESTORE_ARMOR = auto()       # 恢复护甲
    APPLY_BUFF = auto()          # 施加另一个 buff
    REMOVE_BUFF = auto()         # 移除 buff
    EXTEND_COOLDOWN = auto()     # 延长冷却
    REDUCE_COOLDOWN = auto()     # 减少冷却
    STUN = auto()                # 硬直
    INTERRUPT = auto()           # 打断当前动作
    GAIN_ARMOR = auto()          # 获得临时护甲
    CONSUME_STAMINA = auto()     # 消耗体力
    CONSUME_MANA = auto()        # 消耗蓝量
    DODGE_NEXT = auto()          # 闪避下次攻击

@dataclass
class BuffDef:
    """Buff 定义 —— 创建实例的蓝图"""
    name: str
    trigger: TriggerType
    action: AtomicAction
    value: float = 0.0              # 数值 (伤害/治疗/属性变化量)
    target: str = "self"            # self / attacker / all_enemies / all_allies
    duration: float = 0.0           # 持续时间(秒), 0=瞬时/被动
    max_stacks: int = 1             # 最大层数
    interval: float = 0.0           # 触发间隔(秒), ON_TICK 专用
    chance: float = 1.0             # 触发概率 0.0~1.0
    condition: Optional[str] = None # 额外条件 (如 "hp_below_30%")
    description: str = ""

@dataclass
class BuffInstance:
    """Buff 实例 —— 运行时的 buff 状态"""
    definition: BuffDef
    remaining: float                # 剩余时间(秒)
    stacks: int = 1
    last_tick: float = 0.0          # 上次触发时间
    source_id: str = ""             # 来源角色 ID

    @property
    def name(self): return self.definition.name
    @property
    def trigger(self): return self.definition.trigger
    @property
    def expired(self): return self.remaining <= 0 and self.definition.duration > 0

class BuffManager:
    """管理一个 Fighter 身上所有 buff"""

    def __init__(self, owner_id: str):
        self.owner_id = owner_id
        self.buffs: list[BuffInstance] = []

    def apply(self, buff_def: BuffDef, source_id: str = "", duration_override: float = None):
        """施加 buff。已有同名的 → 叠层/刷新时间；新 buff → 添加"""
        dur = duration_override if duration_override is not None else buff_def.duration

        for b in self.buffs:
            if b.definition.name == buff_def.name:
                if b.stacks < buff_def.max_stacks:
                    b.stacks += 1
                b.remaining = max(b.remaining, dur)
                return b

        inst = BuffInstance(definition=buff_def, remaining=dur, source_id=source_id)
        self.buffs.append(inst)
        return inst

    def remove(self, name: str):
        """移除指定名称的 buff"""
        self.buffs = [b for b in self.buffs if b.definition.name != name]

    def get_stat_mod(self, stat: str) -> float:
        """计算某属性的总修正值 (PASSIVE 类型 buff)"""
        total = 0.0
        for b in self.buffs:
            if b.definition.trigger == TriggerType.PASSIVE and b.definition.action == AtomicAction.MODIFY_STAT:
                if stat.upper() in b.definition.name.upper():
                    total += b.definition.value * b.stacks
        return total

    def tick(self, elapsed: float):
        """推进时间——减少持续，触发 ON_TICK"""
        for b in self.buffs:
            if b.definition.duration > 0:
                b.remaining -= elapsed
        # 移除过期 buff
        self.buffs = [b for b in self.buffs if not b.expired]

    def get_triggered(self, trigger: TriggerType, context: dict = None) -> list[BuffInstance]:
        """获取匹配触发条件且满足概率的 buff 列表"""
        import random
        result = []
        for b in self.buffs:
            if b.definition.trigger != trigger:
                continue
            if b.definition.chance < 1.0 and random.random() > b.definition.chance:
                continue
            result.append(b)
        return result

    def has(self, name: str) -> bool:
        return any(b.definition.name == name for b in self.buffs)

    def to_dict(self) -> list[dict]:
        return [{
            "name": b.definition.name,
            "remaining": round(b.remaining, 1),
            "stacks": b.stacks,
            "source": b.source_id,
        } for b in self.buffs if b.definition.duration > 0 and not b.expired]

    def from_dict(self, data: list[dict], buff_library: dict[str, BuffDef]):
        """从存档恢复"""
        self.buffs.clear()
        for d in data:
            if d["name"] in buff_library:
                bd = buff_library[d["name"]]
                inst = BuffInstance(
                    definition=bd,
                    remaining=d.get("remaining", 0),
                    stacks=d.get("stacks", 1),
                    source_id=d.get("source", ""),
                )
                self.buffs.append(inst)
