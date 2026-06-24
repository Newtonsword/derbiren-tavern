"""
Fighter —— 战斗中的单个角色

移植自 combat-engine/index.html 的 Fighter 类 (JavaScript → Python)
新增: BuffManager 集成、装备属性加成、技能冷却追踪
"""

from dataclasses import dataclass, field
from typing import Optional
import random
from .buff import BuffManager, BuffDef, BuffInstance, TriggerType, AtomicAction

# ══════════════════════════════════════════
# 战斗常量（与 combat-engine 一致）
# ══════════════════════════════════════════
TICK = 0.1  # 秒

def hp_from(end: float) -> float:    return end * 200
def stam_from(end: float) -> float:  return end * 50
def mana_from(int_: float) -> float: return int_ * 20
def def_reduce(damage: float, defense: float) -> float:
    return damage * (1 - defense / (defense + 15))
def level_mod(atk_lv: int, def_lv: int) -> float:
    return 1 + (atk_lv - def_lv) * 0.08
def species_resist(coeff: float) -> float:
    return 1 - (coeff - 1) * 0.2

# 伤害类型穿透/破甲参数
DAMAGE_TYPES = {
    "pierce":  {"bypass": 0.10, "armor_dmg_mult": 1.5,  "base_mult": 1.0},
    "blunt":   {"bypass": 0.40, "armor_dmg_mult": 1.0,  "base_mult": 0.85},
    "slash":   {"bypass": 0.20, "armor_dmg_mult": 0.4,  "base_mult": 1.15},
    "fire":    {"bypass": 0.20, "armor_dmg_mult": 0.3,  "base_mult": 1.0},
    "spirit":  {"bypass": 1.0,  "armor_dmg_mult": 0.0,  "base_mult": 1.0},  # 精神攻击无视护甲
}

@dataclass
class SkillCD:
    """技能冷却追踪"""
    name: str
    remaining: int = 0  # tick 倒数
    total: int = 0

@dataclass
class CombatAction:
    """当前正在执行的动作"""
    skill: dict              # 技能数据
    phase: str = "windup"    # windup / recovery
    timer: int = 0           # 剩余 tick

class Fighter:
    """战斗中的单个角色"""

    def __init__(self, cfg: dict, skills: list[dict] = None):
        # ── 基础属性 ──
        self.char_id: str = cfg.get("id", "")
        self.name: str = cfg.get("name", "???")
        self.lv: int = int(cfg.get("level", 1))
        self.species_coeff: float = float(cfg.get("species_coeff", 1.3))  # 物种系数

        # 七属性（可被 buff 修正）
        self._end = float(cfg.get("END", cfg.get("耐力", 4)))
        self._str = float(cfg.get("STR", cfg.get("力量", 4)))
        self._spd = float(cfg.get("SPD", cfg.get("速度", 5)))
        self._df  = float(cfg.get("DEF", cfg.get("防御", 2)))
        self._int = float(cfg.get("INT", cfg.get("智力", 1)))
        self._wil = float(cfg.get("WIL", cfg.get("精神", 4)))
        self._mp  = float(cfg.get("MP", cfg.get("法力", 2)))

        # 装备加成
        equip_bonus = cfg.get("equipment_bonus", {})
        self._end += equip_bonus.get("END", 0) + equip_bonus.get("耐力", 0)
        self._str += equip_bonus.get("STR", 0) + equip_bonus.get("力量", 0)
        self._spd += equip_bonus.get("SPD", 0) + equip_bonus.get("速度", 0)
        self._df  += equip_bonus.get("DEF", 0) + equip_bonus.get("防御", 0)
        self._int += equip_bonus.get("INT", 0) + equip_bonus.get("智力", 0)
        self._wil += equip_bonus.get("WIL", 0) + equip_bonus.get("精神", 0)

        # ── Buff 系统 (必须在派生属性之前初始化) ──
        self.buffs = BuffManager(self.char_id)

        # ── 派生数值 (用裸属性，不受 buff 影响) ──
        self.max_hp = hp_from(self._end)
        self.hp = cfg.get("current_hp") or self.max_hp
        self.max_stamina = stam_from(self._end)
        self.stamina = cfg.get("current_stamina") or self.max_stamina
        self.max_mana = mana_from(self._int)
        self.mana = cfg.get("current_mana") or self.max_mana
        self.collapse = self._wil * 50
        self.max_spirit = self._wil * 10
        self.spirit = cfg.get("current_spirit") or self.max_spirit

        self.max_armor = float(cfg.get("armor", 0) or 0)
        self.armor = cfg.get("current_armor") or self.max_armor

        # ── 战斗状态 ──
        self.team: int = cfg.get("team", 0)  # 0=玩家方 1=敌方
        self.blocking: bool = False
        self.block_value: float = 0.0
        self.stunned: int = 0      # 硬直剩余 tick
        self.lost: bool = False    # 丧失战斗力
        self.state: str = "idle"   # idle / windup / stunned

        # ── 技能 ──
        self.skills: list[dict] = skills or []
        self.cooldowns: dict[str, SkillCD] = {}
        for sk in self.skills:
            cd_ticks = int(sk.get("cooldown", 3.0) / TICK)
            self.cooldowns[sk["name"]] = SkillCD(name=sk["name"], total=cd_ticks)

        self.current_action: Optional[CombatAction] = None

        # ── 被动技能 (从技能列表提取 type="被动" 的) ──
        self._init_passives()

    # ── 属性访问器 (含 buff 修正) ──
    @property
    def end(self): return self._end + self.buffs.get_stat_mod("END")
    @property
    def str(self): return self._str + self.buffs.get_stat_mod("STR")
    @property
    def spd(self): return self._spd + self.buffs.get_stat_mod("SPD")
    @property
    def df(self):  return self._df  + self.buffs.get_stat_mod("DEF")
    @property
    def int_(self): return self._int + self.buffs.get_stat_mod("INT")
    @property
    def wil(self): return self._wil + self.buffs.get_stat_mod("WIL")
    @property
    def mp(self):  return self._mp  + self.buffs.get_stat_mod("MP")

    @property
    def broken(self) -> bool:
        """HP 低于崩盘线 → 伤害减半"""
        return self.hp < self.collapse

    def dmg_multiplier(self) -> float:
        return 0.5 if self.broken else 1.0

    def calc_block(self) -> float:
        """每秒格挡值"""
        return 20 + 2 * self.str + 1 * self.end

    # ── 被动技能初始化 ──
    def _init_passives(self):
        """将技能列表中 type='被动' 的技能转为 buff —— 从 PASSIVE_LIBRARY 查找"""
        from .buff import get_passive_buffs
        for sk in self.skills:
            cat = sk.get("category", sk.get("type", ""))
            if "被动" not in cat:
                continue
            name = sk.get("name", "")
            buffs = get_passive_buffs(name)
            if buffs:
                for bd in buffs:
                    self.buffs.apply(bd, source_id=self.char_id)
            else:
                # 没有预定义的被动 → 尝试旧式文本解析
                effect = sk.get("effect", sk.get("special", ""))
                if effect:
                    self._parse_passive_effect(name, effect)

    def _parse_passive_effect(self, name: str, effect: str):
        """解析被动效果文字 → 转为 BuffDef"""
        import re
        # 例: "偷袭" → 战斗首次攻击伤害×2 → ON_ATTACK_HIT 时判定
        # 例: "闪避本能" → 闪避+10 → PASSIVE MODIFY_STAT
        # 简化处理：按关键字匹配
        if "闪避" in effect:
            m = re.search(r'闪避[+\\-](\\d+)', effect)
            if m:
                bd = BuffDef(name=name, trigger=TriggerType.PASSIVE, action=AtomicAction.DODGE_NEXT,
                            value=float(m.group(1)), description=effect, duration=0)
                self.buffs.apply(bd, source_id=self.char_id)
        if "偷袭" in effect or "首次攻击" in effect:
            bd = BuffDef(name=name, trigger=TriggerType.ON_ATTACK_HIT, action=AtomicAction.DEAL_DAMAGE,
                        value=1.0, description=effect, duration=-1, max_stacks=1,
                        condition="first_attack")
            self.buffs.apply(bd, source_id=self.char_id)

    # ── 伤害管线 ──
    def take_damage(self, raw: float, dmg_type: str = "slash",
                    attacker: "Fighter" = None, is_spirit: bool = False) -> dict:
        """
        完整的伤害计算管线 (与 combat-engine 一致):
          等级修正 → 崩盘减半 → 格挡吸收 → DEF 减伤 → 护甲穿透/吸收 → HP 扣除
        返回: {hp_dmg, blocked, armor_dmg}
        """
        if is_spirit:
            mod = level_mod(attacker.lv, self.lv) * species_resist(self.species_coeff) if attacker else 1.0
            s = raw * mod
            self.spirit -= s
            if self.spirit <= 0:
                self.spirit = 0
                self.lost = True
            return {"hp_dmg": 0, "blocked": 0, "armor_dmg": 0}

        mod = level_mod(attacker.lv, self.lv) if attacker else 1.0
        raw *= mod * self.dmg_multiplier()

        # 被动: 按伤害类型减伤 (硬皮: 钝伤-10%)
        dr = self.buffs.get_passive_value(AtomicAction.DR_BY_TYPE, {"dmg_type": dmg_type})
        if dr:
            raw *= (1.0 - dr)

        # 格挡
        blocked = 0.0
        if self.blocking:
            # 被动: 格挡值倍率 (铁壁: +20%)
            block_mult = self.buffs.get_passive_value(AtomicAction.BLOCK_MULTIPLIER)
            effective_block = self.block_value * (1.0 + block_mult)
            blocked = min(effective_block * TICK, raw)
            raw -= blocked
            if raw > effective_block / 5 and blocked > 0:
                self.blocking = False
                self.state = "stunned"
                self.stunned = 3  # 0.3s 硬直

        if raw <= 0:
            return {"hp_dmg": 0, "blocked": blocked, "armor_dmg": 0}

        # DEF 减伤
        dmg = def_reduce(raw, self.df)

        # 护甲穿透
        dt = DAMAGE_TYPES.get(dmg_type, DAMAGE_TYPES["slash"])
        bypass = dt["bypass"]
        armor_dmg_mult = dt["armor_dmg_mult"]

        bypass_dmg = dmg * bypass
        armor_hit = dmg - bypass_dmg
        hp_dmg = bypass_dmg
        armor_dmg_total = 0.0

        if self.armor > 0:
            absorbed = min(armor_hit, self.armor)
            self.armor -= absorbed
            armor_hit -= absorbed
            hp_dmg += armor_hit
            armor_dmg_total = absorbed * armor_dmg_mult
            self.armor = max(0, self.armor - armor_dmg_total)
        else:
            hp_dmg += armor_hit

        self.hp -= hp_dmg

        # 丧失战斗力判定 (PRD 简化)
        if hp_dmg > 0:
            p = min(hp_dmg / max(self.hp + hp_dmg, 1) * 2, 0.75)
            if random.random() < p * 0.5:
                self.lost = True

        if self.hp <= 0:
            self.hp = 0
            self.lost = True

        return {"hp_dmg": hp_dmg, "blocked": blocked, "armor_dmg": armor_dmg_total}

    # ── 技能相关 ──
    def can_use(self, skill: dict) -> bool:
        """检查技能是否可用"""
        cd = self.cooldowns.get(skill["name"])
        if cd and cd.remaining > 0:
            return False
        if skill.get("stamina_cost", 0) > self.stamina:
            return False
        if skill.get("mana_cost", 0) > self.mana:
            return False
        return True

    def start_action(self, skill: dict):
        """开始执行一个技能动作"""
        w = int(skill.get("windup", 0.3) / TICK)
        self.current_action = CombatAction(skill=skill, phase="windup", timer=w)
        self.state = "windup"

    def use_skill_costs(self, skill: dict):
        """扣除技能消耗"""
        self.stamina = max(0, self.stamina - skill.get("stamina_cost", 0))
        self.mana = max(0, self.mana - skill.get("mana_cost", 0))
        cd_ticks = int(skill.get("cooldown", 3.0) / TICK)
        cd = self.cooldowns.get(skill["name"])
        if cd:
            cd.remaining = cd_ticks

    def tick_cooldowns(self):
        """每 tick 减少冷却"""
        for cd in self.cooldowns.values():
            if cd.remaining > 0:
                cd.remaining -= 1

    def tick_stun(self):
        """每 tick 减少硬直"""
        if self.stunned > 0:
            self.stunned -= 1
            if self.stunned == 0:
                self.state = "idle"

    # ── 序列化 (存档用) ──
    def to_dict(self) -> dict:
        return {
            "char_id": self.char_id,
            "name": self.name,
            "hp": round(self.hp, 1),
            "max_hp": self.max_hp,
            "stamina": round(self.stamina, 1),
            "mana": round(self.mana, 1),
            "spirit": round(self.spirit, 1),
            "armor": round(self.armor, 1),
            "lost": self.lost,
            "buffs": self.buffs.to_dict(),
        }

    def apply_post_combat_state(self, state_dict: dict):
        """战斗结束后恢复状态 (不恢复 HP/护甲等——由每日结算处理)"""
        if "hp" in state_dict:
            self.hp = min(state_dict["hp"], self.max_hp)
        if "stamina" in state_dict:
            self.stamina = min(state_dict["stamina"], self.max_stamina)
        if "spirit" in state_dict:
            self.spirit = min(state_dict["spirit"], self.max_spirit)
        if "armor" in state_dict:
            self.armor = min(state_dict["armor"], self.max_armor)

    def daily_recovery(self):
        """每日恢复——HP/体力/护甲回满，清除负面 buff"""
        self.hp = self.max_hp
        self.stamina = self.max_stamina
        self.mana = self.max_mana
        self.armor = self.max_armor
        self.spirit = self.max_spirit
        self.lost = False
        # 清除持续型 buff (保留 PASSIVE)
        self.buffs.buffs = [b for b in self.buffs.buffs
                           if b.definition.trigger == TriggerType.PASSIVE]
