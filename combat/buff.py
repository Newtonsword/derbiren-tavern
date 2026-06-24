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
    # 被动专用
    DAMAGE_MULTIPLIER = auto()   # 伤害倍率 (value=倍率加成, 如0.25=+25%)
    BLOCK_MULTIPLIER = auto()    # 格挡值倍率
    DR_BY_TYPE = auto()          # 按伤害类型的减伤 (condition指定类型)
    DAMAGE_TAKEN_MULT = auto()   # 受到伤害倍率 (value=倍率, 如0.1=受伤+10%)
    HIT_RATE_MOD = auto()        # 命中率修正
    DODGE_RATE_MOD = auto()      # 闪避率修正
    CLEAVE_RANGE_MOD = auto()    # 溅射范围修正 (米, 正值=增大)
    CLEAVE_RATIO_MOD = auto()    # 溅射伤害比例修正 (如 0.10=+10%比例)

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
    """管理一个角色的所有 buff"""

    def __init__(self, owner_id: str = ""):
        self.buffs: list[BuffInstance] = []
        self.owner_id = owner_id
        self._sim_time: float = 0.0  # 模拟时间, 替代 time.time() 做间隔检查

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

    def get_cleave_range_bonus(self) -> float:
        """溅射范围总修正 (米)。正值=增大溅射范围。"""
        total = 0.0
        for b in self.buffs:
            if b.definition.action == AtomicAction.CLEAVE_RANGE_MOD:
                total += b.definition.value * b.stacks
        return total

    def get_cleave_ratio_bonus(self) -> float:
        """溅射伤害比例总修正。如 0.10=+10% 比例 (加法叠加)。"""
        total = 0.0
        for b in self.buffs:
            if b.definition.action == AtomicAction.CLEAVE_RATIO_MOD:
                total += b.definition.value * b.stacks
        return total

    def tick(self, elapsed: float):
        """推进时间——减少持续，触发 ON_TICK"""
        self._sim_time += elapsed
        for b in self.buffs:
            if b.definition.duration > 0:
                b.remaining -= elapsed
        # 移除过期 buff 及层数耗尽 buff
        self.buffs = [b for b in self.buffs if not b.expired and b.stacks > 0]

    def get_triggered(self, trigger: TriggerType, context: dict = None) -> list[BuffInstance]:
        """获取匹配触发条件且满足概率/间隔的 buff 列表 (使用模拟时间做间隔检查)"""
        import random
        result = []
        for b in self.buffs:
            if b.definition.trigger != trigger:
                continue
            if b.definition.chance < 1.0 and random.random() > b.definition.chance:
                continue
            # 间隔检查 (使用模拟时间, 非墙钟)
            if b.definition.interval > 0:
                elapsed = self._sim_time - b.last_tick
                if elapsed < b.definition.interval:
                    continue
                b.last_tick = self._sim_time
            result.append(b)
        return result

    def has(self, name: str) -> bool:
        return any(b.definition.name == name for b in self.buffs)

    def get_passive_value(self, action: AtomicAction, context: dict = None) -> float:
        """获取某类被动 buff 的合计值，支持条件评估"""
        total = 0.0
        context = context or {}
        for b in self.buffs:
            bd = b.definition
            if bd.action != action:
                continue
            # 条件评估
            if bd.condition and not _eval_condition(bd.condition, context):
                continue
            total += bd.value * b.stacks
        return total

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


# ══════════════════════════════════════════
# 条件评估引擎
# ══════════════════════════════════════════

def _eval_condition(cond: str, ctx: dict) -> bool:
    """评估 buff 触发条件。ctx 由调用方提供 (环境/HP/队友数等)"""
    if not cond:
        return True

    # hp_below_X% → ctx["hp_ratio"] < X/100
    import re
    m = re.search(r'hp_below_(\d+)', cond)
    if m:
        ratio = ctx.get("hp_ratio", 1.0)
        return ratio < int(m.group(1)) / 100.0

    # dmg_type=X → ctx["dmg_type"] == X
    m = re.search(r'dmg_type=(\w+)', cond)
    if m:
        return ctx.get("dmg_type", "") == m.group(1)

    # isolated → ctx["isolated"] == True
    if cond == "isolated":
        return ctx.get("isolated", False)

    # dark_environment → ctx["environment"] == "dark" or "narrow"
    if cond == "dark_environment":
        env = ctx.get("environment", "")
        return env in ("dark", "narrow")

    # first_attack → ctx["first_attack"] == True
    if cond == "first_attack":
        return ctx.get("first_attack", False)

    # ranged_attack → ctx["attack_type"] == "ranged"
    if cond == "ranged_attack":
        return ctx.get("attack_type", "") == "ranged"

    # pack_hunting → ctx["ally_count"] gives multiplier per ally
    if cond == "pack_hunting":
        return ctx.get("ally_count", 0) > 0

    return True


# ══════════════════════════════════════════
# 被动技能库 —— 所有被动效果的 BuffDef 定义
# ══════════════════════════════════════════

PASSIVE_LIBRARY: dict[str, list[BuffDef]] = {
    # ── 重战士 ──
    "铁壁": [
        BuffDef(name="铁壁", trigger=TriggerType.PASSIVE, action=AtomicAction.BLOCK_MULTIPLIER,
                value=0.20, description="格挡值+20%", duration=0),
    ],
    # ── 弓箭手 ──
    "鹰眼": [
        BuffDef(name="鹰眼", trigger=TriggerType.PASSIVE, action=AtomicAction.HIT_RATE_MOD,
                value=0.5, description="远程命中SPD系数+0.5", duration=0,
                condition="ranged_attack"),
    ],
    # ── 哥布林 ──
    "硬皮": [
        BuffDef(name="硬皮", trigger=TriggerType.ON_HIT, action=AtomicAction.DR_BY_TYPE,
                value=0.10, description="钝伤减伤10%", duration=0,
                condition="dmg_type=blunt"),
    ],
    # ── 野狼 ──
    "孤狼": [
        BuffDef(name="孤狼", trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER,
                value=0.15, description="孤立时伤害+15%", duration=0,
                condition="isolated"),
    ],
    "狼群本能": [
        BuffDef(name="狼群本能", trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER,
                value=0.0, description="每个同伴+8%伤害(由引擎动态计算)", duration=0,
                condition="pack_hunting"),
    ],
    # ── 猫龙 ──
    "夜视": [
        BuffDef(name="夜视·命中", trigger=TriggerType.PASSIVE, action=AtomicAction.HIT_RATE_MOD,
                value=15.0, description="黑暗环境命中+15%", duration=0,
                condition="dark_environment"),
        BuffDef(name="夜视·闪避", trigger=TriggerType.PASSIVE, action=AtomicAction.DODGE_RATE_MOD,
                value=15.0, description="黑暗环境闪避+15%", duration=0,
                condition="dark_environment"),
    ],
    # ── 杀人兔 ──
    "狂暴": [
        BuffDef(name="狂暴", trigger=TriggerType.ON_LOW_HP, action=AtomicAction.DAMAGE_MULTIPLIER,
                value=0.25, description="HP<50%时伤害+25%", duration=0,
                condition="hp_below_50"),
    ],
    # ── 触手怪 ──
    "再生": [
        BuffDef(name="再生", trigger=TriggerType.ON_TICK, action=AtomicAction.HEAL_HP,
                value=0, description="每3秒恢复END×2 HP", duration=-1,  # -1=永久
                interval=3.0),
    ],
}

def get_passive_buffs(name: str) -> list[BuffDef]:
    """根据被动技能名获取 BuffDef 列表。复杂被动→多个简单 BuffDef 组合。"""
    return PASSIVE_LIBRARY.get(name, [])


# ══════════════════════════════════════════
# Buff 预设库 —— AI 生成技能时引用的"零件目录"
# ══════════════════════════════════════════
# 用法: skill.effects.on_spirit_break.self = ["spirit_restore_full"]
#       skill.effects.on_spirit_break.target = ["vulnerable_10"]
# 也支持直接写 dict: {"action": "HEAL_SPIRIT", "value": 999}
# 瞬时效果(INSTANT_EFFECTS)在 sim.py 中直接修改属性;
# 持续Buff(BUFF_PRESETS)通过 buffs.apply() 施加。

BUFF_PRESETS: dict[str, BuffDef] = {
    # ══════════════════════════════════════════
    # 七大属性增益 (持续30s, 每属性3档: +3/+5/+8)
    # ══════════════════════════════════════════
    "end_up_3":   BuffDef(name="耐力+3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=3,  duration=30, description="耐力+3"),
    "end_up_5":   BuffDef(name="耐力+5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=5,  duration=30, description="耐力+5"),
    "end_up_8":   BuffDef(name="耐力+8",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=8,  duration=30, description="耐力+8"),
    "str_up_3":   BuffDef(name="力量+3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=3,  duration=30, description="力量+3"),
    "str_up_5":   BuffDef(name="力量+5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=5,  duration=30, description="力量+5"),
    "str_up_8":   BuffDef(name="力量+8",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=8,  duration=30, description="力量+8"),
    "spd_up_3":   BuffDef(name="速度+3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=3,  duration=30, description="速度+3"),
    "spd_up_5":   BuffDef(name="速度+5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=5,  duration=30, description="速度+5"),
    "spd_up_8":   BuffDef(name="速度+8",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=8,  duration=30, description="速度+8"),
    "def_up_3":   BuffDef(name="防御+3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=3,  duration=30, description="防御+3"),
    "def_up_5":   BuffDef(name="防御+5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=5,  duration=30, description="防御+5"),
    "def_up_8":   BuffDef(name="防御+8",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=8,  duration=30, description="防御+8"),
    "int_up_3":   BuffDef(name="智力+3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=3,  duration=30, description="智力+3"),
    "int_up_5":   BuffDef(name="智力+5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=5,  duration=30, description="智力+5"),
    "int_up_8":   BuffDef(name="智力+8",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=8,  duration=30, description="智力+8"),
    "wil_up_3":   BuffDef(name="精神+3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=3,  duration=30, description="精神+3"),
    "wil_up_5":   BuffDef(name="精神+5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=5,  duration=30, description="精神+5"),
    "wil_up_8":   BuffDef(name="精神+8",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=8,  duration=30, description="精神+8"),
    "mp_up_3":    BuffDef(name="法量+3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=3,  duration=30, description="法量+3"),
    "mp_up_5":    BuffDef(name="法量+5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=5,  duration=30, description="法量+5"),
    "mp_up_8":    BuffDef(name="法量+8",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=8,  duration=30, description="法量+8"),

    # ══════════════════════════════════════════
    # 七大属性减益 (持续20s, 每属性2档: -3/-5)
    # ══════════════════════════════════════════
    "end_down_3": BuffDef(name="耐力-3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-3, duration=20, description="耐力-3"),
    "end_down_5": BuffDef(name="耐力-5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-5, duration=20, description="耐力-5"),
    "str_down_3": BuffDef(name="力量-3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-3, duration=20, description="力量-3"),
    "str_down_5": BuffDef(name="力量-5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-5, duration=20, description="力量-5"),
    "spd_down_3": BuffDef(name="速度-3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-3, duration=20, description="速度-3"),
    "spd_down_5": BuffDef(name="速度-5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-5, duration=20, description="速度-5"),
    "def_down_3": BuffDef(name="防御-3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-3, duration=20, description="防御-3"),
    "def_down_5": BuffDef(name="防御-5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-5, duration=20, description="防御-5"),
    "int_down_3": BuffDef(name="智力-3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-3, duration=20, description="智力-3"),
    "int_down_5": BuffDef(name="智力-5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-5, duration=20, description="智力-5"),
    "wil_down_3": BuffDef(name="精神-3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-3, duration=20, description="精神-3"),
    "wil_down_5": BuffDef(name="精神-5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-5, duration=20, description="精神-5"),
    "mp_down_3":  BuffDef(name="法量-3",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-3, duration=20, description="法量-3"),
    "mp_down_5":  BuffDef(name="法量-5",   trigger=TriggerType.PASSIVE, action=AtomicAction.MODIFY_STAT, value=-5, duration=20, description="法量-5"),

    # ══════════════════════════════════════════
    # 伤害倍率 — 全局 (持续30s)
    # ══════════════════════════════════════════
    "damage_up_15":  BuffDef(name="伤害+15%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER, value=0.15, duration=30, description="伤害+15%"),
    "damage_up_25":  BuffDef(name="伤害+25%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER, value=0.25, duration=30, description="伤害+25%"),
    "damage_up_40":  BuffDef(name="伤害+40%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER, value=0.40, duration=30, description="伤害+40%"),
    "damage_down_15": BuffDef(name="伤害-15%", trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER, value=-0.15, duration=20, description="伤害-15%"),
    "damage_down_25": BuffDef(name="伤害-25%", trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER, value=-0.25, duration=20, description="伤害-25%"),

    # ══════════════════════════════════════════
    # 伤害倍率 — 按类型 (condition=dmg_type=X, 持续30s)
    # ══════════════════════════════════════════
    "damage_up_slash_15":    BuffDef(name="斩伤+15%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER, value=0.15, duration=30, condition="dmg_type=slash",   description="斩击伤害+15%"),
    "damage_up_slash_25":    BuffDef(name="斩伤+25%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER, value=0.25, duration=30, condition="dmg_type=slash",   description="斩击伤害+25%"),
    "damage_up_pierce_15":   BuffDef(name="刺伤+15%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER, value=0.15, duration=30, condition="dmg_type=pierce",  description="刺击伤害+15%"),
    "damage_up_pierce_25":   BuffDef(name="刺伤+25%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER, value=0.25, duration=30, condition="dmg_type=pierce",  description="刺击伤害+25%"),
    "damage_up_blunt_15":    BuffDef(name="钝伤+15%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER, value=0.15, duration=30, condition="dmg_type=blunt",   description="钝击伤害+15%"),
    "damage_up_blunt_25":    BuffDef(name="钝伤+25%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER, value=0.25, duration=30, condition="dmg_type=blunt",   description="钝击伤害+25%"),
    "damage_up_spirit_15":   BuffDef(name="精神伤+15%",trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER, value=0.15, duration=30, condition="dmg_type=spirit",  description="精神伤害+15%"),
    "damage_up_spirit_25":   BuffDef(name="精神伤+25%",trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_MULTIPLIER, value=0.25, duration=30, condition="dmg_type=spirit",  description="精神伤害+25%"),

    # ══════════════════════════════════════════
    # 按类型减伤 (DR_BY_TYPE, condition=dmg_type=X, 持续30s)
    # ══════════════════════════════════════════
    "dr_slash_15":    BuffDef(name="斩抗+15%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DR_BY_TYPE, value=0.15, duration=30, condition="dmg_type=slash",   description="受到斩伤-15%"),
    "dr_slash_30":    BuffDef(name="斩抗+30%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DR_BY_TYPE, value=0.30, duration=30, condition="dmg_type=slash",   description="受到斩伤-30%"),
    "dr_pierce_15":   BuffDef(name="刺抗+15%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DR_BY_TYPE, value=0.15, duration=30, condition="dmg_type=pierce",  description="受到刺伤-15%"),
    "dr_pierce_30":   BuffDef(name="刺抗+30%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DR_BY_TYPE, value=0.30, duration=30, condition="dmg_type=pierce",  description="受到刺伤-30%"),
    "dr_blunt_15":    BuffDef(name="钝抗+15%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DR_BY_TYPE, value=0.15, duration=30, condition="dmg_type=blunt",   description="受到钝伤-15%"),
    "dr_blunt_30":    BuffDef(name="钝抗+30%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DR_BY_TYPE, value=0.30, duration=30, condition="dmg_type=blunt",   description="受到钝伤-30%"),
    "dr_spirit_15":   BuffDef(name="精抗+15%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DR_BY_TYPE, value=0.15, duration=30, condition="dmg_type=spirit",  description="受到精神伤-15%"),
    "dr_spirit_30":   BuffDef(name="精抗+30%",  trigger=TriggerType.PASSIVE, action=AtomicAction.DR_BY_TYPE, value=0.30, duration=30, condition="dmg_type=spirit",  description="受到精神伤-30%"),

    # ══════════════════════════════════════════
    # 受伤倍率 (易伤/坚韧, 持续30s)
    # ══════════════════════════════════════════
    "vulnerable_10": BuffDef(name="易伤",      trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_TAKEN_MULT, value=0.10, duration=30, description="受伤+10%"),
    "vulnerable_25": BuffDef(name="重伤",      trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_TAKEN_MULT, value=0.25, duration=30, description="受伤+25%"),
    "tough_15":      BuffDef(name="坚韧",      trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_TAKEN_MULT, value=-0.15, duration=30, description="受伤-15%"),
    "tough_30":      BuffDef(name="铁壁",      trigger=TriggerType.PASSIVE, action=AtomicAction.DAMAGE_TAKEN_MULT, value=-0.30, duration=30, description="受伤-30%"),

    # ══════════════════════════════════════════
    # 格挡倍率 (持续30s)
    # ══════════════════════════════════════════
    "block_up_30": BuffDef(name="格挡+30%", trigger=TriggerType.PASSIVE, action=AtomicAction.BLOCK_MULTIPLIER, value=0.30, duration=30, description="格挡值+30%"),
    "block_up_50": BuffDef(name="格挡+50%", trigger=TriggerType.PASSIVE, action=AtomicAction.BLOCK_MULTIPLIER, value=0.50, duration=30, description="格挡值+50%"),

    # ══════════════════════════════════════════
    # 命中/闪避 (持续30s)
    # ══════════════════════════════════════════
    "hit_up_10":   BuffDef(name="精准",       trigger=TriggerType.PASSIVE, action=AtomicAction.HIT_RATE_MOD,  value=10, duration=30, description="命中+10"),
    "hit_up_20":   BuffDef(name="鹰眼",       trigger=TriggerType.PASSIVE, action=AtomicAction.HIT_RATE_MOD,  value=20, duration=30, description="命中+20"),
    "dodge_up_10": BuffDef(name="灵巧",       trigger=TriggerType.PASSIVE, action=AtomicAction.DODGE_RATE_MOD, value=10, duration=30, description="闪避+10"),
    "dodge_up_20": BuffDef(name="幻影",       trigger=TriggerType.PASSIVE, action=AtomicAction.DODGE_RATE_MOD, value=20, duration=30, description="闪避+20"),
    "hit_down_10": BuffDef(name="盲目",       trigger=TriggerType.PASSIVE, action=AtomicAction.HIT_RATE_MOD,  value=-10, duration=20, description="命中-10"),
    "dodge_down_10": BuffDef(name="迟缓",     trigger=TriggerType.PASSIVE, action=AtomicAction.DODGE_RATE_MOD, value=-10, duration=20, description="闪避-10"),

    # ══════════════════════════════════════════
    # 护甲 (临时护甲, 持续30s)
    # ══════════════════════════════════════════
    "armor_up_30":  BuffDef(name="护甲+30",  trigger=TriggerType.PASSIVE, action=AtomicAction.GAIN_ARMOR, value=30,  duration=30, description="护甲+30"),
    "armor_up_50":  BuffDef(name="护甲+50",  trigger=TriggerType.PASSIVE, action=AtomicAction.GAIN_ARMOR, value=50,  duration=30, description="护甲+50"),
    "armor_up_100": BuffDef(name="护甲+100", trigger=TriggerType.PASSIVE, action=AtomicAction.GAIN_ARMOR, value=100, duration=30, description="护甲+100"),

    # ══════════════════════════════════════════
    # 持续恢复 (ON_TICK, 永久持续, value=0由引擎按END动态计算)
    # ══════════════════════════════════════════
    "regen_hp_2s":   BuffDef(name="再生·速",   trigger=TriggerType.ON_TICK, action=AtomicAction.HEAL_HP, value=0, duration=-1, interval=2.0, description="每2秒恢复END×2 HP"),
    "regen_hp_3s":   BuffDef(name="再生",       trigger=TriggerType.ON_TICK, action=AtomicAction.HEAL_HP, value=0, duration=-1, interval=3.0, description="每3秒恢复END×2 HP"),
    "regen_hp_5s":   BuffDef(name="再生·缓",   trigger=TriggerType.ON_TICK, action=AtomicAction.HEAL_HP, value=0, duration=-1, interval=5.0, description="每5秒恢复END×2 HP"),
    "regen_stam_2s": BuffDef(name="耐力恢复",   trigger=TriggerType.ON_TICK, action=AtomicAction.HEAL_STAMINA, value=0, duration=-1, interval=2.0, description="每2秒恢复END×2 体力"),

    # ══════════════════════════════════════════
    # 控制效果 (ON_ATTACK_HIT)
    # ══════════════════════════════════════════
    "stun_on_hit_05s": BuffDef(name="钝击", trigger=TriggerType.ON_ATTACK_HIT, action=AtomicAction.STUN, value=0.5, duration=0, description="命中时硬直0.5s"),
    "stun_on_hit_1s":  BuffDef(name="重击", trigger=TriggerType.ON_ATTACK_HIT, action=AtomicAction.STUN, value=1.0, duration=0, description="命中时硬直1s"),

    # ══════════════════════════════════════════
    # 持续性伤害 DoT (ON_TICK + DEAL_DAMAGE)
    # condition 控制衰减模式:
    #   "dot"=每跳层数-1(毒), "dot_halve"=每跳层数减半(燃烧),
    #   "dot_nodecay"=层数不减(固定持续伤害)
    # ══════════════════════════════════════════
    # ── 层数-1型 (中毒: 伤害稳定递减) ──
    "dot_poison_3":  BuffDef(name="中毒",  trigger=TriggerType.ON_TICK, action=AtomicAction.DEAL_DAMAGE, value=3, duration=-1, interval=1.0, max_stacks=10, condition="dot", description="每秒3×层毒伤,层数-1"),
    "dot_poison_5":  BuffDef(name="剧毒",  trigger=TriggerType.ON_TICK, action=AtomicAction.DEAL_DAMAGE, value=5, duration=-1, interval=1.0, max_stacks=10, condition="dot", description="每秒5×层毒伤,层数-1"),
    # ── 层数减半型 (燃烧: 伤害快速衰减, 每次减半) ──
    "dot_burn_4":    BuffDef(name="燃烧",  trigger=TriggerType.ON_TICK, action=AtomicAction.DEAL_DAMAGE, value=4, duration=-1, interval=1.0, max_stacks=8,  condition="dot_halve", description="每秒4×层燃烧,层数减半"),
    "dot_burn_6":    BuffDef(name="烈焰",  trigger=TriggerType.ON_TICK, action=AtomicAction.DEAL_DAMAGE, value=6, duration=-1, interval=1.0, max_stacks=8,  condition="dot_halve", description="每秒6×层燃烧,层数减半"),
    # ── 层数不减型 (固定持续伤害, 靠duration到期) ──
    "dot_bleed_2":   BuffDef(name="流血",  trigger=TriggerType.ON_TICK, action=AtomicAction.DEAL_DAMAGE, value=2, duration=10, interval=1.0, max_stacks=1,  condition="dot_nodecay", description="每秒2点流血,持续10秒"),
    "dot_bleed_4":   BuffDef(name="大出血",trigger=TriggerType.ON_TICK, action=AtomicAction.DEAL_DAMAGE, value=4, duration=10, interval=1.0, max_stacks=1,  condition="dot_nodecay", description="每秒4点流血,持续10秒"),

    # ══════════════════════════════════════════
    # 溅射修正 (CLEAVE_RANGE_MOD / CLEAVE_RATIO_MOD, 持续30s)
    # ══════════════════════════════════════════
    # ── 溅射范围 (+/- 米) ──
    "cleave_range_up_1":   BuffDef(name="横扫",   trigger=TriggerType.PASSIVE, action=AtomicAction.CLEAVE_RANGE_MOD, value=1.0,  duration=30, description="溅射范围+1m"),
    "cleave_range_up_2":   BuffDef(name="旋风斩", trigger=TriggerType.PASSIVE, action=AtomicAction.CLEAVE_RANGE_MOD, value=2.0,  duration=30, description="溅射范围+2m"),
    "cleave_range_down_1": BuffDef(name="拘束",   trigger=TriggerType.PASSIVE, action=AtomicAction.CLEAVE_RANGE_MOD, value=-1.0, duration=20, description="溅射范围-1m"),
    # ── 溅射比例 (+/- 百分点) ──
    "cleave_ratio_up_10":  BuffDef(name="裂伤",   trigger=TriggerType.PASSIVE, action=AtomicAction.CLEAVE_RATIO_MOD, value=0.10, duration=30, description="溅射伤害比例+10%"),
    "cleave_ratio_up_20":  BuffDef(name="粉碎",   trigger=TriggerType.PASSIVE, action=AtomicAction.CLEAVE_RATIO_MOD, value=0.20, duration=30, description="溅射伤害比例+20%"),
    "cleave_ratio_down_10":BuffDef(name="收束",   trigger=TriggerType.PASSIVE, action=AtomicAction.CLEAVE_RATIO_MOD, value=-0.10,duration=20, description="溅射伤害比例-10%"),
}


# ══════════════════════════════════════════
# 瞬时效果 —— 一次性生效，不产生持续 Buff
# ══════════════════════════════════════════
# key → {"action": str, "value": float}
# 支持的行动: HEAL_HP, HEAL_SPIRIT, HEAL_STAMINA, RESTORE_ARMOR, STUN
INSTANT_EFFECTS: dict[str, dict] = {
    # ── 瞬时回血 ──
    "heal_hp_30":     {"action": "HEAL_HP", "value": 30},
    "heal_hp_50":     {"action": "HEAL_HP", "value": 50},
    "heal_hp_100":    {"action": "HEAL_HP", "value": 100},
    "heal_hp_50pct":  {"action": "HEAL_HP_PCT", "value": 0.5},   # 特殊: 百分比回血

    # ── 瞬时回精神 ──
    "spirit_restore_full": {"action": "HEAL_SPIRIT", "value": 9999},
    "spirit_restore_50":   {"action": "HEAL_SPIRIT", "value": 50},
    "spirit_restore_30":   {"action": "HEAL_SPIRIT", "value": 30},

    # ── 瞬时回蓝 ──
    "mana_restore_full": {"action": "HEAL_MANA", "value": 9999},
    "mana_restore_50":   {"action": "HEAL_MANA", "value": 50},
    "mana_restore_30":   {"action": "HEAL_MANA", "value": 30},

    # ── 瞬时回体力 ──
    "stamina_restore_full": {"action": "HEAL_STAMINA", "value": 9999},
    "stamina_restore_50":   {"action": "HEAL_STAMINA", "value": 50},

    # ── 瞬时硬直 ──
    "stun_05s": {"action": "STUN", "value": 0.5},
    "stun_1s":  {"action": "STUN", "value": 1.0},
    "stun_2s":  {"action": "STUN", "value": 2.0},
}


def resolve_effect(effect):
    """将 effect 字符串或 dict 解析为可执行的 (type, data) 元组。
    
    返回:
      ("instant", {action, value})  — 瞬时效果
      ("buff", BuffDef)             — 持续 buff
      None — 无法解析
    """
    if isinstance(effect, str):
        # 引用预设名
        if effect in INSTANT_EFFECTS:
            return ("instant", INSTANT_EFFECTS[effect])
        if effect in BUFF_PRESETS:
            return ("buff", BUFF_PRESETS[effect])
        return None
    if isinstance(effect, dict):
        action = effect.get("action", "")
        # 如果 action 是 BUFF_PRESETS 里的 key → 持续 buff
        if action in BUFF_PRESETS:
            # 允许覆盖 duration
            bd = BUFF_PRESETS[action]
            dur = effect.get("duration", bd.duration)
            return ("buff", BuffDef(
                name=bd.name, trigger=bd.trigger, action=bd.action,
                value=bd.value * effect.get("value_mult", 1.0),
                duration=dur, description=bd.description,
                interval=bd.interval,
            ))
        # 如果 action 是 INSTANT_EFFECTS 里的 key → 瞬时
        if action in INSTANT_EFFECTS:
            ie = dict(INSTANT_EFFECTS[action])
            if "value" in effect:
                ie["value"] = effect["value"]
            return ("instant", ie)
        # 否则直接作为字典使用
        return ("instant", effect)
    return None
