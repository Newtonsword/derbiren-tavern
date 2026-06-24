"""
CombatSim v2 —— 0.1s tick 战斗模拟器 (含距离/位置/移动系统)

程序主导:
  - 时间推进 (每 tick = 0.1s)
  - 位置管理 (PositionManager: 距离/移动/风筝)
  - 冷却/硬直递减
  - 动作管线 (前摇 → 判定 → 后摇 → 冷却)
  - 防御自动触发 (反应式, 不可主动使用)
  - 伤害计算
  - 胜负判定

AI 只负责:
  - 技能选择 (通过回调函数 ai_skill_picker)
  - 选技使用质量分 + 动态调整 + 智力影响

输出:
  - tick 级战斗日志
  - CombatResult (胜者、双方最终状态、经验)
"""

from dataclasses import dataclass, field
from typing import Callable, Optional
import random
from .fighter import Fighter, TICK, CombatAction
from .buff import TriggerType, AtomicAction
from .position import PositionManager, MELEE_RANGE
from .ai import clear_quality_cache

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
    cls: str = ""  # hit / spirit / result / block / stun / move / dist

class CombatSim:
    """战斗模拟器 v2 —— 含距离/位置/自动防御"""

    def __init__(self, team0: list[Fighter], team1: list[Fighter],
                 environment: str = "open",
                 ai_skill_picker: Callable = None,
                 max_ticks: int = 2000):
        """
        team0: 玩家方 Fighter 列表
        team1: 敌方 Fighter 列表
        environment: "open" | "field" | "narrow" | "arena"
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

        # ── 位置系统 ──
        self.positions = PositionManager(team0, team1, environment)

        # ── 清除质量分缓存 ──
        clear_quality_cache()

    # ── 默认 AI ──
    async def _default_async_pick(self, fighter: Fighter,
                                   enemies: list[Fighter],
                                   allies: list[Fighter]) -> Optional[dict]:
        from .ai import scored_pick_v2
        return scored_pick_v2(fighter, enemies, allies, self.positions)

    # ── 主循环 ──
    async def run(self) -> CombatResult:
        """运行战斗模拟直到一方全灭或超时"""
        env_names = {"open": "开阔地(100m)", "field": "原野(50m)",
                     "narrow": "狭窄洞穴(30m)", "arena": "竞技场(20m)"}
        env_desc = env_names.get(self.environment, self.environment)
        self._add_log(0, f"⚡ 战斗开始！{self._team_summary()} | 环境:{env_desc}", "result")

        # 触发 ON_COMBAT_START
        for f in self.all_fighters:
            for b in f.buffs.get_triggered(TriggerType.ON_COMBAT_START):
                self._execute_buff_action(f, b, None, f)

        # 开局距离日志
        self._log_distances()

        while self.tick < self.max_ticks:
            # 检查胜负
            t0_alive = any(not f.lost for f in self.team0)
            t1_alive = any(not f.lost for f in self.team1)

            if not t0_alive:
                self._add_log(self.tick, "💀 玩家方全灭 — 敌方获胜！", "result")
                break
            if not t1_alive:
                self._add_log(self.tick, "🏆 敌方全灭 — 玩家获胜！", "result")
                break

            if self.tick >= self.max_ticks:
                self._add_log(self.tick, "⏰ 战斗超时 — 平局", "result")
                break

            # ── 1. 位置移动阶段 ──
            self.positions.tick(self.team0, self.team1)

            # ── 2. 推进所有 Fighter 状态 ──
            for f in self.all_fighters:
                if f.lost:
                    continue
                f.tick_cooldowns()
                f.tick_stun()
                f.buffs.tick(TICK)

                # ON_TICK 被动 (再生等持续恢复)
                for b in f.buffs.get_triggered(TriggerType.ON_TICK):
                    if b.action == AtomicAction.HEAL_HP:
                        heal = f.end * 2
                        f.hp = min(f.max_hp, f.hp + heal)
                        self._add_log(self.tick,
                            f"💚 {f.name} [再生] HP+{heal:.0f} → {f.hp:.0f}", "heal")

                # 体力/蓝量自然恢复
                f.stamina = min(f.max_stamina, f.stamina + 0.1)
                f.mana = min(f.max_mana, f.mana + 0.05)

            # ── 3. 自动防御阶段 (反应式: 检测敌方蓄力 → 自动格挡) ──
            self._process_auto_defense()

            # ── 4. 动作管线 ──
            for f in self.all_fighters:
                if f.lost or f.state == "stunned":
                    continue
                self._process_action(f)

            # ── 5. AI 选技 ──
            for f in self.all_fighters:
                if f.lost or f.state != "idle" or f.current_action is not None:
                    continue

                enemies = self.team1 if f.team == 0 else self.team0
                allies = self.team0 if f.team == 0 else self.team1
                skill = await self.ai_picker(f, enemies, allies)

                if skill and f.can_use(skill):
                    # 距离检查: 近战必须在近战距离内
                    stype = skill.get("type", "")
                    if not skill.get("ranged") and stype != "spirit":
                        live_enemies = [e for e in enemies if not e.lost]
                        if live_enemies:
                            closest = min(live_enemies,
                                key=lambda e: self.positions.distance(f, e))
                            if not self.positions.can_melee(f, closest):
                                continue  # 太远, 跳过这次选技 (等下个 tick)
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
            log=[{"tick": e.tick, "time": e.time, "msg": e.msg, "cls": e.cls}
                 for e in self.log],
        )

    # ── 自动防御 ──
    def _process_auto_defense(self):
        """
        检测所有正在蓄力的攻击者 → 目标自动使用防御技能。

        规则:
          - 遍历所有处于 windup 阶段的 Fighter
          - 找到他们的攻击目标
          - 如果目标有可用的防御技能 → 自动触发
          - 防御技能消耗照常扣除
          - 防御是瞬时的 (无前摇), 但有后摇冷却
        """
        for attacker in self.all_fighters:
            if attacker.lost:
                continue
            act = attacker.current_action
            if act is None or act.phase != "windup":
                continue

            skill = act.skill
            stype = skill.get("type", "")

            # 只对攻击性技能触发防御 (防御技/精神攻击不触发)
            if stype in ("defense", "spirit"):
                continue

            # 确定目标
            enemies = self.team1 if attacker.team == 0 else self.team0
            target = self._pick_target(attacker, enemies, skill)
            if not target or target.lost:
                continue

            # 目标是否已经在执行动作?
            if target.current_action is not None or target.state != "idle":
                continue

            # 目标是否有可用的防御技能?
            def_skill = None
            for sk in target.skills:
                if sk.get("type") == "defense" and target.can_use(sk):
                    def_skill = sk
                    break

            if def_skill is None:
                continue

            # 自动触发防御
            block_val = self._calc_skill_damage(target, def_skill)
            target.block_value = block_val
            target.blocking = True
            target.use_skill_costs(def_skill)
            # 反应式防御是瞬时的, 不改变 fighter 的 state

            self._add_log(self.tick,
                f"🛡️ {target.name} [{def_skill['name']}] 格挡值 +{block_val:.0f} "
                f"(反应式, 对 {attacker.name} 的 {skill['name']})",
                "block")

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
        stype = skill.get("type", "")
        is_ranged = bool(skill.get("ranged"))

        if act.phase == "windup":
            # ── 判定帧 ──

            # 防御技: 已被自动防御接管, 此处作为 fallback
            if stype == "defense":
                block_val = self._calc_skill_damage(fighter, skill)
                fighter.block_value = block_val
                fighter.blocking = True
                self._add_log(self.tick,
                    f"🛡️ {fighter.name} [{skill['name']}] 格挡值 +{block_val:.0f}",
                    "block")
                act.phase = "recovery"
                act.timer = int(skill.get("recovery", 0.5) / TICK)
                return

            enemies = self.team1 if fighter.team == 0 else self.team0
            target = self._pick_target(fighter, enemies, skill)
            if target and not target.lost:
                self._execute_hit(fighter, target, skill)
            act.phase = "recovery"

            # 距离惩罚: 远程在近战范围前后摇翻倍
            recovery = skill.get("recovery", 0.5)
            if is_ranged and target:
                penalty = self.positions.ranged_penalty(fighter, target)
                if penalty < 1.0:
                    recovery *= 2.0  # 近战用远程, 后摇翻倍
            act.timer = int(recovery / TICK)
        else:
            # 后摇结束 → 进入冷却
            fighter.use_skill_costs(skill)
            fighter.current_action = None
            fighter.state = "idle"

    # ── 目标选择 ──
    def _pick_target(self, attacker: Fighter, enemies: list[Fighter],
                     skill: dict) -> Optional[Fighter]:
        """选择目标: 优先最近存活敌人"""
        live = [e for e in enemies if not e.lost]
        if not live:
            return None
        # 按距离排序, 优先最近的
        return min(live, key=lambda e: self.positions.distance(attacker, e))

    # ── 命中判定与伤害 ──
    def _execute_hit(self, attacker: Fighter, target: Fighter, skill: dict):
        """执行一次攻击判定"""
        dmg_type = skill.get("type", "slash")
        is_ranged = bool(skill.get("ranged"))

        # 精神攻击
        if dmg_type == "spirit":
            raw = self._calc_skill_damage(attacker, skill)
            result = target.take_damage(raw, dmg_type, attacker, is_spirit=True)
            self._add_log(self.tick,
                f"🔮 {attacker.name} [{skill['name']}] 精神伤害{raw:.0f} → "
                f"{target.name}精神条{target.spirit:.0f}/{target.max_spirit}",
                "spirit")
            return

        # ── 距离惩罚: 远程在近战范围命中率减半 ──
        hit_chance = self._calc_hit_chance(attacker, target, skill)
        if is_ranged:
            pen = self.positions.ranged_penalty(attacker, target)
            hit_chance *= pen

        if random.random() * 100 > hit_chance:
            self._add_log(self.tick,
                f"💨 {attacker.name} [{skill['name']}] 未命中 → {target.name} "
                f"(命中率{hit_chance:.0f}%)",
                "miss")
            # 闪避也触发 stagger
            self.positions.stagger(target)
            for b in attacker.buffs.get_triggered(TriggerType.ON_ATTACK_MISS):
                self._execute_buff_action(attacker, b, attacker, target)
            return

        # 伤害计算
        raw = self._calc_skill_damage(attacker, skill)
        result = target.take_damage(raw, dmg_type, attacker)

        dist = self.positions.distance(attacker, target)
        dist_tag = ""
        if is_ranged and dist <= MELEE_RANGE:
            dist_tag = " [近战范围·命中半减]"

        self._add_log(self.tick,
            f"⚔️ {attacker.name} [{skill['name']}] {raw:.0f} → {target.name} "
            f"HP-{result['hp_dmg']:.0f}(格挡{result['blocked']:.0f}) "
            f"HP{target.hp:.0f} 护甲{target.armor:.0f} 距离{dist:.1f}m{dist_tag}",
            "hit")

        # ── 命中 stagger: 被命中者速度减半 0.3s ──
        self.positions.stagger(target)

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
            formula = formula.replace("×", "*").replace(" ", "")
            ns = {
                "END": fighter.end, "STR": fighter.str, "SPD": fighter.spd,
                "DEF": fighter.df, "INT": fighter.int_, "WIL": fighter.wil,
                "MP": fighter.mp,
                "耐力": fighter.end, "力量": fighter.str, "速度": fighter.spd,
                "防御": fighter.df, "智力": fighter.int_, "精神": fighter.wil,
                "法量": fighter.mp,
                "min": min, "max": max, "abs": abs, "round": round,
            }
            try:
                base = float(eval(formula, {"__builtins__": {}}, ns))
            except Exception:
                base = 30 + 2 * fighter.str + 1 * fighter.spd

        # 被动伤害倍率
        ctx = self._build_dmg_context(fighter)
        dmg_mult = fighter.buffs.get_passive_value(AtomicAction.DAMAGE_MULTIPLIER, ctx)
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

        hit_ctx = self._build_hit_context(attacker, skill)
        hit_mod = attacker.buffs.get_passive_value(AtomicAction.HIT_RATE_MOD, hit_ctx)
        base_hit += hit_mod

        dodge = target.spd * 1.5
        dodge_ctx = self._build_dodge_context(target)
        dodge_mod = target.buffs.get_passive_value(AtomicAction.DODGE_RATE_MOD, dodge_ctx)
        dodge += dodge_mod

        if self.environment == "narrow":
            if skill.get("type") == "spirit":
                dodge += 5

        hit = base_hit - dodge
        return max(5, min(95, hit))

    # ── Buff 动作执行 ──
    def _execute_buff_action(self, owner: Fighter, buff_inst, source: Fighter,
                             target: Fighter):
        bd = buff_inst.definition
        action = bd.action
        val = bd.value * buff_inst.stacks

        if action == AtomicAction.DEAL_DAMAGE:
            target.take_damage(val, "slash", source)
            self._add_log(self.tick,
                f"✨ [{bd.name}] 附加 {val:.0f} 伤害 → {target.name}", "hit")
        elif action == AtomicAction.HEAL_HP:
            owner.hp = min(owner.max_hp, owner.hp + val)
            self._add_log(self.tick,
                f"💚 [{bd.name}] 恢复 {val:.0f} HP → {owner.name}", "heal")
        elif action == AtomicAction.HEAL_STAMINA:
            owner.stamina = min(owner.max_stamina, owner.stamina + val)
        elif action == AtomicAction.STUN:
            target.stunned = int(val / TICK)
            self._add_log(self.tick,
                f"💫 [{bd.name}] {target.name} 硬直 {val}s", "stun")
        elif action == AtomicAction.GAIN_ARMOR:
            owner.armor = min(owner.max_armor, owner.armor + val)
            self._add_log(self.tick,
                f"🛡️ [{bd.name}] +{val:.0f} 护甲", "block")
        elif action == AtomicAction.DODGE_NEXT:
            owner.buffs.apply(bd, source_id=source.char_id, duration_override=999)

    # ── 日志 ──
    def _add_log(self, tick: int, msg: str, cls: str = ""):
        self.log.append(CombatLogEntry(
            tick=tick, time=round(tick * TICK, 1), msg=msg, cls=cls))

    def _team_summary(self) -> str:
        t0 = ", ".join(f"{f.name}(Lv.{f.lv})" for f in self.team0)
        t1 = ", ".join(f"{f.name}(Lv.{f.lv})" for f in self.team1)
        return f"[{t0}] vs [{t1}]"

    def _log_distances(self):
        """记录开局距离信息"""
        for f0 in self.team0:
            for f1 in self.team1:
                d = self.positions.distance(f0, f1)
                self._add_log(0,
                    f"📍 {f0.name} ↔ {f1.name}: {d:.1f}m", "dist")

    # ── 被动条件上下文构建 ──
    def _build_dmg_context(self, fighter: Fighter) -> dict:
        allies = self.team0 if fighter.team == 0 else self.team1
        live_allies = [a for a in allies
                       if not a.lost and a.char_id != fighter.char_id]
        return {
            "hp_ratio": fighter.hp / fighter.max_hp if fighter.max_hp else 1.0,
            "isolated": len(live_allies) == 0,
            "ally_count": len(live_allies),
            "environment": self.environment,
        }

    def _build_hit_context(self, fighter: Fighter, skill: dict) -> dict:
        has_eagle = any(b.definition.name == "鹰眼"
                       for b in fighter.buffs.buffs)
        is_ranged = skill.get("ranged") or (
            has_eagle and skill.get("type") in ("pierce",)
        )
        return {
            "environment": self.environment,
            "attack_type": "ranged" if is_ranged else "melee",
        }

    def _build_dodge_context(self, fighter: Fighter) -> dict:
        return {"environment": self.environment}
