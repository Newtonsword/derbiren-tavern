"""
CombatSim —— 0.1s tick 战斗模拟器

程序主导:
  - 时间推进 (每 tick = 0.1s)
  - 冷却/硬直递减
  - 动作管线 (前摇 → 判定 → 后摇 → 冷却)
  - 伤害计算
  - 胜负判定

AI 只负责:
  - 技能选择 (通过回调函数 ai_skill_picker)

输出:
  - tick 级战斗日志
  - CombatResult (胜者、双方最终状态、经验)
"""

from dataclasses import dataclass, field
from typing import Callable, Optional
import random
from .fighter import Fighter, TICK, CombatAction
from .buff import TriggerType, AtomicAction

@dataclass
class CombatResult:
    """战斗结果"""
    victor_team: int           # 获胜队伍 (0 或 1)
    duration: float            # 战斗时长(秒)
    total_ticks: int
    team0_survivors: list[dict]  # 幸存者状态
    team1_survivors: list[dict]
    all_fighters_final: list[dict]  # 所有 Fighter 最终状态
    log: list[dict]            # tick 级日志

@dataclass
class CombatLogEntry:
    tick: int
    time: float
    msg: str
    cls: str = ""  # hit / spirit / result / block / stun

class CombatSim:
    """战斗模拟器"""

    def __init__(self, team0: list[Fighter], team1: list[Fighter],
                 environment: str = "open",
                 ai_skill_picker: Callable = None,
                 max_ticks: int = 2000):
        """
        team0: 玩家方 Fighter 列表
        team1: 敌方 Fighter 列表
        environment: "open" | "narrow" (狭窄洞穴)
        ai_skill_picker: async (fighter, enemies, allies) -> skill_name
        max_ticks: 最大 tick 数 (2000 = 200 秒)
        """
        self.team0 = team0
        self.team1 = team1
        self.all_fighters = team0 + team1
        self.environment = environment
        self.ai_picker = ai_skill_picker or self._default_async_pick
        self.max_ticks = max_ticks
        self.log: list[CombatLogEntry] = []
        self.tick = 0

    # ── 默认 AI (简单: 选第一个可用的技能) ──
    async def _default_async_pick(self, fighter: Fighter,
                                   enemies: list[Fighter],
                                   allies: list[Fighter]) -> Optional[dict]:
        return self._default_ai_pick(fighter, enemies, allies)

    def _default_ai_pick(self, fighter: Fighter,
                         enemies: list[Fighter],
                         allies: list[Fighter]) -> Optional[dict]:
        """默认 AI —— 选第一个可用技能"""
        live_enemies = [e for e in enemies if not e.lost]
        if not live_enemies:
            return None
        for sk in fighter.skills:
            if sk.get("type") == "防御" or sk.get("category") == "被动":
                continue
            if fighter.can_use(sk):
                return sk
        return None

    # ── 主循环 ──
    async def run(self) -> CombatResult:
        """运行战斗模拟直到一方全灭或超时"""
        self._add_log(0, f"⚡ 战斗开始！{self._team_summary()} | 环境:{'狭窄洞穴' if self.environment == 'narrow' else '开阔地'}")

        # 触发 ON_COMBAT_START
        for f in self.all_fighters:
            for b in f.buffs.get_triggered(TriggerType.ON_COMBAT_START):
                self._execute_buff_action(f, b, None, f)

        while self.tick < self.max_ticks:
            # 检查胜负
            t0_alive = any(not f.lost for f in self.team0)
            t1_alive = any(not f.lost for f in self.team1)

            if not t0_alive:
                self._add_log(self.tick, f"💀 玩家方全灭 — 敌方获胜！", "result")
                break
            if not t1_alive:
                self._add_log(self.tick, f"🏆 敌方全灭 — 玩家获胜！", "result")
                break

            # 每 50 tick 检查超时平局
            if self.tick >= self.max_ticks:
                self._add_log(self.tick, "⏰ 战斗超时 — 平局", "result")
                break

            # ── 推进所有 Fighter 状态 ──
            for f in self.all_fighters:
                if f.lost:
                    continue
                f.tick_cooldowns()
                f.tick_stun()
                f.buffs.tick(TICK)

                # ON_TICK 被动 (再生等持续恢复)
                for b in f.buffs.get_triggered(TriggerType.ON_TICK):
                    if b.action == AtomicAction.HEAL_HP:
                        # 再生: 恢复 END×2 HP
                        heal = f.end * 2
                        f.hp = min(f.max_hp, f.hp + heal)
                        self._add_log(self.tick,
                            f"💚 {f.name} [再生] HP+{heal:.0f} → {f.hp:.0f}", "heal")

                # 体力/蓝量自然恢复 (少量)
                f.stamina = min(f.max_stamina, f.stamina + 0.1)
                f.mana = min(f.max_mana, f.mana + 0.05)

            # ── 动作管线 ──
            for f in self.all_fighters:
                if f.lost or f.state == "stunned":
                    continue
                self._process_action(f)

            # ── AI 选技 ──
            for f in self.all_fighters:
                if f.lost or f.state != "idle" or f.current_action is not None:
                    continue

                enemies = self.team1 if f.team == 0 else self.team0
                allies = self.team0 if f.team == 0 else self.team1
                skill = await self.ai_picker(f, enemies, allies)

                if skill and f.can_use(skill):
                    f.start_action(skill)

            self.tick += 1

        # ── 结果 ──
        t0_alive = any(not f.lost for f in self.team0)
        t1_alive = any(not f.lost for f in self.team1)

        if not t0_alive:
            victor = 1
        elif not t1_alive:
            victor = 0
        else:
            victor = -1  # 平局

        return CombatResult(
            victor_team=victor,
            duration=round(self.tick * TICK, 1),
            total_ticks=self.tick,
            team0_survivors=[f.to_dict() for f in self.team0 if not f.lost],
            team1_survivors=[f.to_dict() for f in self.team1 if not f.lost],
            all_fighters_final=[f.to_dict() for f in self.all_fighters],
            log=[{"tick": e.tick, "time": e.time, "msg": e.msg, "cls": e.cls} for e in self.log],
        )

    # ── 动作管线处理 ──
    def _process_action(self, fighter: Fighter):
        """处理 Fighter 当前动作的一个 tick"""
        act = fighter.current_action
        if act is None:
            return

        act.timer -= 1
        if act.timer > 0:
            return  # 动作还在进行中

        skill = act.skill
        if act.phase == "windup":
            # 判定帧 —— 伤害生效
            enemies = self.team1 if fighter.team == 0 else self.team0
            target = self._pick_target(fighter, enemies, skill)
            if target and not target.lost:
                self._execute_hit(fighter, target, skill)
            act.phase = "recovery"
            act.timer = int(skill.get("recovery", 0.5) / TICK)
        else:
            # 后摇结束 → 进入冷却
            fighter.use_skill_costs(skill)
            fighter.current_action = None
            fighter.state = "idle"

    # ── 目标选择 ──
    def _pick_target(self, attacker: Fighter, enemies: list[Fighter], skill: dict) -> Optional[Fighter]:
        """选择目标。默认: 最近的存活的敌人"""
        live = [e for e in enemies if not e.lost]
        if not live:
            return None
        # 优先选择 HP 最低的 (简化 AI)
        return min(live, key=lambda e: e.hp)

    # ── 命中判定与伤害 ──
    def _execute_hit(self, attacker: Fighter, target: Fighter, skill: dict):
        """执行一次攻击判定"""
        dmg_type = skill.get("type", "slash")

        # 精神攻击
        if dmg_type == "spirit":
            raw = self._calc_skill_damage(attacker, skill)
            result = target.take_damage(raw, dmg_type, attacker, is_spirit=True)
            self._add_log(self.tick,
                f"🔮 {attacker.name} [{skill['name']}] 精神伤害{raw:.0f} → "
                f"{target.name}精神条{target.spirit:.0f}/{target.max_spirit}",
                "spirit")
            return

        # 命中判定
        hit_chance = self._calc_hit_chance(attacker, target, skill)
        if random.random() * 100 > hit_chance:
            self._add_log(self.tick,
                f"💨 {attacker.name} [{skill['name']}] 未命中 → {target.name}",
                "miss")
            # 触发 ON_ATTACK_MISS
            for b in attacker.buffs.get_triggered(TriggerType.ON_ATTACK_MISS):
                self._execute_buff_action(attacker, b, attacker, target)
            return

        # 伤害计算
        raw = self._calc_skill_damage(attacker, skill)
        result = target.take_damage(raw, dmg_type, attacker)

        self._add_log(self.tick,
            f"⚔️ {attacker.name} [{skill['name']}] {raw:.0f} → {target.name} "
            f"HP-{result['hp_dmg']:.0f}(格挡{result['blocked']:.0f}) "
            f"HP{target.hp:.0f} 护甲{target.armor:.0f}",
            "hit")

        # 触发 ON_ATTACK_HIT (攻击方)
        for b in attacker.buffs.get_triggered(TriggerType.ON_ATTACK_HIT):
            self._execute_buff_action(attacker, b, attacker, target)

        # 触发 ON_HIT (受击方)
        for b in target.buffs.get_triggered(TriggerType.ON_HIT):
            self._execute_buff_action(target, b, target, attacker)

        # 击杀触发
        if target.lost:
            self._add_log(self.tick,
                f"💀 {target.name} 丧失战斗力！", "result")
            for b in attacker.buffs.get_triggered(TriggerType.ON_KILL):
                self._execute_buff_action(attacker, b, attacker, target)

    # ── 伤害公式计算 ──
    def _calc_skill_damage(self, fighter: Fighter, skill: dict) -> float:
        """根据技能公式计算原始伤害 (含被动伤害倍率)"""
        formula = skill.get("formula", skill.get("dmg_formula", ""))
        if not formula:
            base = 30 + 2 * fighter.str + 1 * fighter.spd
        else:
            ns = {
                "END": fighter.end, "STR": fighter.str, "SPD": fighter.spd,
                "DEF": fighter.df, "INT": fighter.int_, "WIL": fighter.wil,
                "MP": fighter.mp,
                "耐力": fighter.end, "力量": fighter.str, "速度": fighter.spd,
                "防御": fighter.df, "智力": fighter.int_, "精神": fighter.wil,
                "min": min, "max": max, "abs": abs, "round": round,
            }
            try:
                base = float(eval(formula, {"__builtins__": {}}, ns))
            except Exception:
                base = 30 + 2 * fighter.str + 1 * fighter.spd

        # 被动伤害倍率 (孤狼/狂暴/狼群本能等)
        ctx = self._build_dmg_context(fighter)
        dmg_mult = fighter.buffs.get_passive_value(AtomicAction.DAMAGE_MULTIPLIER, ctx)
        # 狼群本能: 每个同伴×8%
        if ctx.get("ally_count", 0) > 0:
            for b in fighter.buffs.buffs:
                if b.definition.condition == "pack_hunting":
                    dmg_mult += 0.08 * ctx["ally_count"] * b.stacks
        if dmg_mult:
            base *= (1.0 + dmg_mult)
        return base

    def _calc_hit_chance(self, attacker: Fighter, target: Fighter, skill: dict) -> float:
        """计算命中率 (5%~95%, 含被动命中/闪避修正)"""
        hit_formula = skill.get("hit_formula", "")
        if hit_formula:
            ns = {
                "END": attacker.end, "STR": attacker.str, "SPD": attacker.spd,
                "DEF": attacker.df, "INT": attacker.int_, "WIL": attacker.wil,
                "MP": attacker.mp,
            }
            try:
                base_hit = float(eval(hit_formula, {"__builtins__": {}}, ns))
            except Exception:
                base_hit = 85
        else:
            base_hit = 75 + attacker.spd * 2.5

        # 被动命中修正 (鹰眼/夜视等)
        hit_ctx = self._build_hit_context(attacker, skill)
        hit_mod = attacker.buffs.get_passive_value(AtomicAction.HIT_RATE_MOD, hit_ctx)
        base_hit += hit_mod

        # 目标闪避 (SPD × 1.5)
        dodge = target.spd * 1.5

        # 被动闪避修正 (夜视等)
        dodge_ctx = self._build_dodge_context(target)
        dodge_mod = target.buffs.get_passive_value(AtomicAction.DODGE_RATE_MOD, dodge_ctx)
        dodge += dodge_mod

        # 环境修正
        if self.environment == "narrow":
            if skill.get("type") == "spirit":
                dodge += 5

        hit = base_hit - dodge
        return max(5, min(95, hit))

    # ── Buff 动作执行 ──
    def _execute_buff_action(self, owner: Fighter, buff_inst, source: Fighter, target: Fighter):
        """执行 buff 的原子动作"""
        bd = buff_inst.definition
        action = bd.action
        val = bd.value * buff_inst.stacks

        if action == AtomicAction.DEAL_DAMAGE:
            target.take_damage(val, "slash", source)
            self._add_log(self.tick, f"✨ [{bd.name}] 附加 {val:.0f} 伤害 → {target.name}", "hit")
        elif action == AtomicAction.HEAL_HP:
            owner.hp = min(owner.max_hp, owner.hp + val)
            self._add_log(self.tick, f"💚 [{bd.name}] 恢复 {val:.0f} HP → {owner.name}", "heal")
        elif action == AtomicAction.HEAL_STAMINA:
            owner.stamina = min(owner.max_stamina, owner.stamina + val)
        elif action == AtomicAction.STUN:
            target.stunned = int(val / TICK)
            self._add_log(self.tick, f"💫 [{bd.name}] {target.name} 硬直 {val}s", "stun")
        elif action == AtomicAction.GAIN_ARMOR:
            owner.armor = min(owner.max_armor, owner.armor + val)
            self._add_log(self.tick, f"🛡️ [{bd.name}] +{val:.0f} 护甲", "block")
        elif action == AtomicAction.DODGE_NEXT:
            # 下次被攻击时闪避 (在 take_damage 前检查)
            owner.buffs.apply(bd, source_id=source.char_id, duration_override=999)

    # ── 日志 ──
    def _add_log(self, tick: int, msg: str, cls: str = ""):
        self.log.append(CombatLogEntry(tick=tick, time=round(tick * TICK, 1), msg=msg, cls=cls))

    def _team_summary(self) -> str:
        t0 = ", ".join(f"{f.name}(Lv.{f.lv})" for f in self.team0)
        t1 = ", ".join(f"{f.name}(Lv.{f.lv})" for f in self.team1)
        return f"[{t0}] vs [{t1}]"

    # ── 被动条件上下文构建 ──
    def _build_dmg_context(self, fighter: Fighter) -> dict:
        """构建伤害被动条件上下文 (孤狼/狂暴/狼群)"""
        allies = self.team0 if fighter.team == 0 else self.team1
        live_allies = [a for a in allies if not a.lost and a.char_id != fighter.char_id]
        return {
            "hp_ratio": fighter.hp / fighter.max_hp if fighter.max_hp else 1.0,
            "isolated": len(live_allies) == 0,
            "ally_count": len(live_allies),
            "environment": self.environment,
        }

    def _build_hit_context(self, fighter: Fighter, skill: dict) -> dict:
        """构建命中被动条件上下文 (鹰眼/夜视)"""
        # 鹰眼持有者的刺击视为远程
        has_eagle = any(b.definition.name == "鹰眼" for b in fighter.buffs.buffs)
        is_ranged = skill.get("ranged") or (
            has_eagle and skill.get("type") in ("pierce",)
        )
        return {
            "environment": self.environment,
            "attack_type": "ranged" if is_ranged else "melee",
        }

    def _build_dodge_context(self, fighter: Fighter) -> dict:
        """构建闪避被动条件上下文 (夜视)"""
        return {"environment": self.environment}
