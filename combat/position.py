"""
PositionManager —— 战斗位置/距离/移动系统

设计:
  - 一维坐标 (x轴), 单位: 米
  - 每 tick 移动: speed × TICK
  - 移动速度 = 2.0 + SPD × 0.3 (m/s)
  - 被命中(伤害/格挡/闪避) → 0.3s 内速度减半
  - 地图边界: 由 environment 决定 (open=100, field=50, narrow=30, arena=20)
  - 开局站位: 双方相距 map_width/3, 远程站后排
"""

from dataclasses import dataclass, field
from typing import Optional
from .fighter import TICK
from .skill import normalize_type

# 地图尺寸映射 (米)
MAP_SIZES = {
    "open": 100,
    "field": 50,
    "narrow": 30,
    "arena": 20,
}

# 近战距离阈值 (米) —— 小于此值视为近战范围
MELEE_RANGE = 2.0
# 远程舒适距离 (米) —— 远程角色试图保持的距离
RANGED_COMFORT_MIN = 5.0
RANGED_COMFORT_MAX = 15.0
# 近战角色追击距离 —— 超过此值放弃追击改为搜索新目标
MELEE_CHASE_MAX = 30.0


@dataclass
class FighterPosition:
    """单个 Fighter 的位置状态"""
    char_id: str
    x: float = 0.0                  # 当前 x 坐标
    stagger_timer: int = 0          # 被命中后速度减半剩余 tick
    base_speed: float = 0.0         # 基础移动速度 (m/s)
    preferred_range: float = 2.0    # 偏好交战距离 (近战=2, 远程=8)
    is_ranged: bool = False         # 是否远程角色

    @property
    def current_speed(self) -> float:
        """当前移动速度: 受 stagger 影响"""
        if self.stagger_timer > 0:
            return self.base_speed * 0.5
        return self.base_speed

    def tick_stagger(self):
        """每 tick 减少 stagger"""
        if self.stagger_timer > 0:
            self.stagger_timer -= 1


class PositionManager:
    """
    管理战斗中所有角色的位置和距离。

    使用方式:
        pm = PositionManager(team0_fighters, team1_fighters, environment="open")
        # 每 tick:
        pm.tick()  # 推进移动
        dist = pm.distance(f1, f2)
        pm.stagger(fighter)  # 被命中时调用
    """

    def __init__(self, team0: list, team1: list,
                 environment: str = "open"):
        """
        team0: Fighter 列表 (玩家方)
        team1: Fighter 列表 (敌方)
        environment: "open" | "field" | "narrow" | "arena"
        """
        self.map_width = MAP_SIZES.get(environment, 50)
        self.environment = environment
        self.positions: dict[str, FighterPosition] = {}

        # ── 初始化位置 ──
        # 开局间距: 地图的 1/3
        gap = self.map_width / 3
        team0_start = gap
        team1_start = self.map_width - gap

        self._init_team(team0, team0_start, 0)
        self._init_team(team1, team1_start, 1)

    def _init_team(self, fighters: list, base_x: float, team: int):
        """初始化一队的位置。远程站后排 (±2m 纵深)。"""
        ranged_fighters = []
        melee_fighters = []

        for f in fighters:
            if f.lost:
                continue
            is_ranged = self._is_ranged(f)
            if is_ranged:
                ranged_fighters.append(f)
            else:
                melee_fighters.append(f)

        # 近战在前, 远程在后
        offset_dir = -1 if team == 0 else 1  # team0面向右, team1面向左
        back_offset = 3.0 * offset_dir

        for i, f in enumerate(melee_fighters):
            spread = (i - (len(melee_fighters) - 1) / 2) * 1.5
            x = base_x + spread
            self.positions[f.char_id] = FighterPosition(
                char_id=f.char_id,
                x=x,
                base_speed=2.0 + f.spd * 0.3,
                preferred_range=MELEE_RANGE,
                is_ranged=False,
            )

        for i, f in enumerate(ranged_fighters):
            spread = (i - (len(ranged_fighters) - 1) / 2) * 1.5
            x = base_x + back_offset + spread
            self.positions[f.char_id] = FighterPosition(
                char_id=f.char_id,
                x=x,
                base_speed=2.0 + f.spd * 0.3,
                preferred_range=RANGED_COMFORT_MIN,
                is_ranged=True,
            )

    def _is_ranged(self, fighter) -> bool:
        """判断是否是远程角色: 技能列表中多数为远程"""
        ranged_count = 0
        total = 0
        for sk in fighter.skills:
            cat = sk.get("category", "")
            stype = sk.get("type", "")
            if cat == "被动" or normalize_type(stype) == "defense":
                continue
            total += 1
            if sk.get("ranged"):
                ranged_count += 1
        return ranged_count > total / 2 if total > 0 else False

    def distance(self, f1, f2) -> float:
        """两个角色之间的距离 (米)"""
        p1 = self.positions.get(f1.char_id)
        p2 = self.positions.get(f2.char_id)
        if not p1 or not p2:
            return 0.0
        return abs(p1.x - p2.x)

    def at_melee_range(self, f1, f2) -> bool:
        """是否在近战距离内"""
        return self.distance(f1, f2) <= MELEE_RANGE

    def at_ranged_comfort(self, f1, f2) -> bool:
        """是否在远程舒适距离内"""
        d = self.distance(f1, f2)
        return RANGED_COMFORT_MIN <= d <= RANGED_COMFORT_MAX

    def closest_enemy(self, fighter, enemies: list) -> Optional[object]:
        """返回距离最近的存活敌人"""
        live = [e for e in enemies if not e.lost]
        if not live:
            return None
        return min(live, key=lambda e: self.distance(fighter, e))

    def stagger(self, fighter):
        """被命中时调用: 0.3s 内速度减半"""
        pos = self.positions.get(fighter.char_id)
        if pos:
            pos.stagger_timer = int(0.3 / TICK)  # 3 ticks

    def nearby_enemies(self, fighter, enemies: list, max_range: float) -> list:
        """返回 fighter 周围 max_range 米内的存活敌人（不含 fighter 自己）"""
        if fighter.lost:
            return []
        live = [e for e in enemies if not e.lost and e.char_id != fighter.char_id]
        return [e for e in live if self.distance(fighter, e) <= max_range]

    def tick_movement(self, fighter, enemies: list):
        """
        每 tick 推进一个角色的移动。

        移动逻辑:
          - 近战: 向最近敌人移动，直到进入近战范围
          - 远程: 保持舒适距离，太近后退，太远前进
          - 受地图边界限制
          - 受 stagger 影响
        """
        if fighter.lost:
            return

        pos = self.positions.get(fighter.char_id)
        if not pos:
            return

        pos.tick_stagger()

        live_enemies = [e for e in enemies if not e.lost]
        if not live_enemies:
            return

        target = self.closest_enemy(fighter, live_enemies)
        if not target:
            return

        target_pos = self.positions.get(target.char_id)
        if not target_pos:
            return

        dist = self.distance(fighter, target)
        move_amount = pos.current_speed * TICK

        if pos.is_ranged:
            # 远程: 保持 5-15m
            if dist < RANGED_COMFORT_MIN:
                # 太近 → 后退
                direction = -1 if pos.x > target_pos.x else 1
                pos.x = self._clamp(pos.x + direction * move_amount)
            elif dist > RANGED_COMFORT_MAX:
                # 太远 → 前进
                direction = 1 if target_pos.x > pos.x else -1
                pos.x = self._clamp(pos.x + direction * move_amount)
            # 在舒适距离 → 不动，准备攻击
        else:
            # 近战: 向目标移动
            if dist > MELEE_RANGE:
                direction = 1 if target_pos.x > pos.x else -1
                pos.x = self._clamp(pos.x + direction * move_amount)
            # 已在近战范围 → 不动，准备攻击

    def tick(self, team0: list, team1: list):
        """每 tick 推进所有角色的移动"""
        for f in team0:
            self.tick_movement(f, team1)
        for f in team1:
            self.tick_movement(f, team0)

    def can_melee(self, fighter, target) -> bool:
        """近战技能是否可用: 必须在近战距离内"""
        return self.at_melee_range(fighter, target)

    def can_ranged(self, fighter, target) -> bool:
        """远程技能是否可用: 任何距离都可以，但近战范围有惩罚"""
        return True  # 远程技能可以在任何距离使用，只是近战有惩罚

    def ranged_penalty(self, fighter, target) -> float:
        """
        远程技能在近战距离的惩罚系数。
        返回 1.0 = 无惩罚, 0.5 = 命中减半
        """
        if self.at_melee_range(fighter, target):
            return 0.5
        return 1.0

    def _clamp(self, x: float) -> float:
        """限制在地图边界内"""
        return max(0.0, min(self.map_width, x))

    def get_summary(self) -> dict:
        """返回位置摘要 (用于日志/AI 上下文)"""
        result = {}
        for cid, pos in self.positions.items():
            result[cid] = {
                "x": round(pos.x, 1),
                "speed": round(pos.current_speed, 1),
                "stagger": pos.stagger_timer > 0,
                "ranged": pos.is_ranged,
            }
        return result
