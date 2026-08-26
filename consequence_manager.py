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


# 巡逻遭遇事件池——保证巡逻每次都有戏唱，防止 AI 自由发挥绕死。
# 每个事件带三样「方向预设」字段，GM 叙述时有谱不绕死：
#   direction   → 事件所属方向（GM 知道往哪个主轴演）
#   gm_hook     → 给 GM 的叙述指引：怎么展开、怎么收、别碰什么数据
#   reward_hint → 玩家能预判的收益倾向（项目铁律：可预判才不空转）
# kind 区分处理方式：
#   encounter → 触发遭遇战（[ENCOUNTER] 标签，真程序战斗）
#   event     → 纯叙事遭遇（[EVENT] 标签，GM 叙述 + 给选择，不改世界状态）
PATROL_EVENT_POOL = [
    # ── ⚔️ 战斗入侵方向 ──
    {"kind": "encounter", "id": "ambush_adventurer", "name": "落单冒险者",
     "direction": "战斗入侵", "desc": "巡逻时撞见一名落单的冒险者，他正鬼鬼祟祟地在你的领地边缘摸索。对方也发现了你，拔剑迎了上来!",
     "gm_hook": "直接切换遭遇战模式，让玩家选迎战/逃跑。不附加额外选项，专注一场干脆的对决。",
     "reward_hint": "战利品+领地威慑，队伍安然则士气+",
     "enemy": {"name": "落单冒险者", "species": "人类", "level": 3,
               "stats": {"END":3,"STR":4,"SPD":3,"DEF":2,"INT":2,"MP":2,"WIL":3},
               "skills_raw": "挥砍:斩击:15+2.0×力量+0.5×速度:耐力14:3.0s"}},
    {"kind": "encounter", "id": "stray_bandit", "name": "流窜盗匪",
     "direction": "战斗入侵", "desc": "地道岔路口传来低语——两名流窜盗匪正围着篝火分赃，警惕地盯着路过的你。",
     "gm_hook": "遭遇战。对方人数占优但散漫，若玩家想偷袭/绕道可给体现速度的额外选项，本质仍是战斗。",
     "reward_hint": "战利品，或缴获盗匪赃物",
     "enemy": {"name": "流窜盗匪", "species": "人类", "level": 4,
               "stats": {"END":4,"STR":5,"SPD":4,"DEF":3,"INT":2,"MP":2,"WIL":3},
               "skills_raw": "挥砍:斩击:16+2.0×力量+0.5×速度:耐力14:3.0s;偷袭:刺击:18+2.0×速度+0.5×力量:耐力12:2.5s"}},
    {"kind": "encounter", "id": "mimic_treasure", "name": "伪装宝箱",
     "direction": "战斗入侵", "desc": "巡逻道上摆着一口精致宝箱，镶着金边、缝隙里透出怪异的蠕动。经验告诉你——这是只模仿怪!",
     "gm_hook": "遭遇战。玩家可先识破（需高智力/警觉），识破可选绕开或伏击；未识破直接开打。",
     "reward_hint": "打赢收获真宝箱，识破可避免损耗",
     "enemy": {"name": "模仿怪", "species": "魔物", "level": 5,
               "stats": {"END":5,"STR":5,"SPD":3,"DEF":5,"INT":2,"MP":2,"WIL":3},
               "skills_raw": "噬咬:斩击:20+2.5×力量+0.5×速度:耐力16:3.5s;毒液:刺击:15+1.0×智力:耐力14:4.0s"}},
    {"kind": "encounter", "id": "suspicious_swarm", "name": "可疑虫群",
     "direction": "战斗入侵", "desc": "一批庞大虫群堵住了巡逻通道，发出令人毛骨悚然的咀嚼声，受惊后转身朝你涌来!",
     "gm_hook": "遭遇战。虫群速度快但脆，强调速度压制；若玩家队伍里有火属性魔物可提优势。",
     "reward_hint": "战利品，虫壳/酸液可作制作材料",
     "enemy": {"name": "地穴虫群", "species": "魔物", "level": 3,
               "stats": {"END":3,"STR":3,"SPD":6,"DEF":1,"INT":1,"MP":1,"WIL":2},
               "skills_raw": "撕裂:斩击:14+1.5×速度+0.5×力量:耐力10:2.0s"}},
    {"kind": "encounter", "id": "sensei_bat", "name": "精英暗影蝠",
     "direction": "战斗入侵", "desc": "巡逻道顶传来沉重的振翅声——一只体型远超寻常的暗影蝠悬停在头顶，双眼猩红，明显是这片区域的精英个体。",
     "gm_hook": "遭遇战。精英敌人血厚攻高，给玩家「准备弹药/布阵」的提示但不改变战斗本质。",
     "reward_hint": "高价值战利品，蝠翼/精英素材",
     "enemy": {"name": "精英暗影蝠", "species": "魔物", "level": 5,
               "stats": {"END":4,"STR":5,"SPD":7,"DEF":3,"INT":3,"MP":3,"WIL":4},
               "skills_raw": "声波突袭:斩击:19+2.0×速度+0.5×力量:耐力14:2.5s;吸血撕咬:终结:22+2.5×力量:耐力18:4.0s"}},

    # ── 🛡️ 招募结盟方向 ──
    {"kind": "event", "id": "wounded_adventurer", "name": "受伤冒险者",
     "direction": "招募结盟", "desc": "巡逻时在角落发现一名身受重伤的冒险者，他抓着你的衣角哀求救治，并许诺报酬。救，还是不救?",
     "gm_hook": "道德抉择。给选择：救治（获报酬/名声）/弃之（零消耗但传恶名）/审问（获情报但要耗资源）。走 NPC 关系链。",
     "reward_hint": "救→报酬/名声；弃→零耗但恶名",
     },
    {"kind": "event", "id": "lost_cub", "name": "走失幼崽",
     "direction": "招募结盟", "desc": "巡逻时听到一阵细碎的呜咽——一只魔物幼崽蜷缩在墙角发抖，看来是和族群走散了，见到你既害怕又期待。",
     "gm_hook": "招募向。给选择：收养（后续可成新队员，走 RECRUIT 链）/救助送回家（赢族群好感）/喂食遣散（结善缘）。走 npc_persona 关系链。",
     "reward_hint": "可招募新魔物，或赢族群好感",
     },
    {"kind": "event", "id": "roaming_golem", "name": "流浪石傀儡",
     "direction": "招募结盟", "desc": "巡逻时撞见一只无主的流浪石傀儡，笨拙地在一处矿坑边徘徊，看起来想找个地方安顿下来。",
     "gm_hook": "招募向。给选择：招揽（+1防御型队员）/赠它一块矿石讨好/绕开。走 RECRUIT 链，强调它高防低敏特性适合当壁垒。",
     "reward_hint": "可招募的高防魔物守护者",
     },

    # ── 🏗️ 基建发展方向 ──
    {"kind": "event", "id": "new_trail", "name": "未开掘的岔道口",
     "direction": "基建发展", "desc": "巡逻到领地边缘时，发现一条被落石半掩的岔道口——土是新的，痕迹是新的，仿佛正等着第一位主人来开凿。",
     "gm_hook": "发展向。给选择：投入开凿（扩展领地/新房间，需资源）/标记待办（记录后续可建）/先勘探（得情报）。引出基建链。",
     "reward_hint": "领地扩张、新功能房间",
     },
    {"kind": "event", "id": "spring_cave", "name": "地底温泉口",
     "direction": "基建发展", "desc": "巡逻时一股热气扑面而来——岩壁裂开一道缝隙，渗出温暖的地下水，是处天然温泉眼。",
     "gm_hook": "发展/休整向。给选择：规划建浴场（长期恢复/士气设施）/先引流饮用（短期收益）/封存观察。引出基建链。",
     "reward_hint": "可建休整设施，队伍持续恢复",
     },
    {"kind": "event", "id": "crystal_vein", "name": "荧光矿脉",
     "direction": "基建发展", "desc": "通道墙面浮现一片幽幽蓝光——是一条裸露的荧光矿脉，质地细密，是锻造与附魔的好材料。",
     "gm_hook": "发展/资源向。给选择：组织开采（获建造/锻造材料）/标记矿点（记录待开采）/估量不碰（安全）。引材料链。",
     "reward_hint": "锻造/附魔材料，支持后续建造",
     },

    # ── 💎 资源机遇方向 ──
    {"kind": "event", "id": "mysterious_merchant", "name": "神秘商人",
     "direction": "资源机遇", "desc": "一团紫色烟雾在巡逻道前凝成一名戴着兜帽的商人，他打开布满奇异花纹的箱子，压低声音向你兜售「好东西」。",
     "gm_hook": "交易向。货真价实或坑人随玩家观察力/砍价走，给选择：买/物物交换/拒绝。有赚有赔的风险收益。",
     "reward_hint": "稀有装备/材料，但有被宰风险",
     },
    {"kind": "event", "id": "stash_cache", "name": "遗落补给箱",
     "direction": "资源机遇", "desc": "巡逻道旁的杂草堆里露出一只半埋的铁箱，箱扣松动，像是谁匆忙遗落的。",
     "gm_hook": "资源向。给选择：开启（随机得补给/材料，可能触发小惊喜或小陷阱）/不碰（安全）。开箱奖励链。",
     "reward_hint": "随机补给/材料，小概率遭暗算",
     },
    {"kind": "event", "id": "gem_cluster", "name": "闪光宝石簇",
     "direction": "资源机遇", "desc": "巡逻时地面上反射出细碎的光——一簇天然宝石嵌在岩缝里，纯度很高，价值不菲。",
     "gm_hook": "资源向。给选择：小心凿取（得宝石，可能惊动看护魔物）/只取几颗（风险低收益小）/标记待采。资源链。",
     "reward_hint": "高价值宝石，小概率遭遇守卫",
     },

    # ── 🌩️ 危机征兆方向 ──
    {"kind": "event", "id": "omen_caw", "name": "窥视的鸦群",
     "direction": "危机征兆", "desc": "巡逻时一群黑鸦高高盘绕在你头顶，既不远遁也不俯冲，只是静静打量——像是在给谁通风报信。",
     "gm_hook": "预警向。给选择：驱散（防盯梢）/伪装行踪（误导跟踪者）/暗中追踪鸦群（反查出窥视者）。走预警情报链。",
     "reward_hint": "预知被监视→提前反制",
     },
    {"kind": "event", "id": "ominous_tracks", "name": "陌生的足印",
     "direction": "危机征兆", "desc": "巡逻道边的苔藓上印着一串陌生足印——尺寸巨大、趾爪尖锐，明显不属于你的任何魔物，且是新鲜的。",
     "gm_hook": "预警向。给选择：循迹追踪（可能是强敌或机会）/撤退上报（暂避锋芒）/布下陷阱（伏击未知之物）。危机链。",
     "reward_hint": "预警→追踪可得宝或遇强敌",
     },

    # ── 📜 秘辛探索方向 ──
    {"kind": "event", "id": "omen_ritual", "name": "诡异祭坛",
     "direction": "秘辛探索", "desc": "巡逻道的尽头凭空升起一座石质祭坛，周围散布着新鲜兽骨和冰冷烛火。一阵低语随风飘来，像是召唤着什么。",
     "gm_hook": "秘辛向。给选择：献祭（可能获秘法/引祸）/虔诚参拜（获一缕祝福或警告）/毁掉（除祸源）。走世界观秘辛链。",
     "reward_hint": "秘法/祝福，或触发隐藏祸端",
     },
    {"kind": "event", "id": "ancient_rune", "name": "上古符文碑",
     "direction": "秘辛探索", "desc": "巡逻墙角立着一块风化严重的石碑，上面刻着发光的符文——是上古时代魔王们留下的某种传承，仿佛在等待能读懂它的人。",
     "gm_hook": "秘辛向。给选择：研读（需高智力，可能获传承技艺/世界观）/拓印保存（留档）/不动（安全）。引导世界观。",
     "reward_hint": "传承技艺、世界观史料",
     },
    {"kind": "event", "id": "lost_tomb", "name": "半掩的古墓",
     "direction": "秘辛探索", "desc": "巡逻时一处坍塌的岩壁后面露出一角石门——是座古老的墓室，门上刻着你是谁都不想招惹的符号。",
     "gm_hook": "秘辛向。给选择：小心开启（获古物/惊动守墓之物）/封回原样（避祸）/记下位置（待强时再来）。秘辛链。",
     "reward_hint": "古物/隐藏宝藏，或惊动守护者",
     },

    # ── 🫂 情感羁绊方向 ──
    {"kind": "event", "id": "collapsed_passage", "name": "坍塌通道",
     "direction": "情感羁绊", "desc": "前方通道突然剧烈震动，轰的一声塌方了——一块巨石滚落堵死了整条巡逻路。你听见塌方后面传来微弱的呼救声。",
     "gm_hook": "羁绊向。给选择：全力救援（可能救出受困者/获忠诚与好感，需耗资源）/稳妥清理（慢但安全）/绕道（袖手旁观埋恶名）。走 NPC 关系链。",
     "reward_hint": "救助→忠诚/好感；绕道→恶名",
     },
    {"kind": "event", "id": "homesick_rookie", "name": "想家的新兵",
     "direction": "情感羁绊", "desc": "巡逻归途中，你注意到队里那只刚加入不久的小魔物情绪低落，独自坐在角落发呆——它似乎想家了。",
     "gm_hook": "羁绊向。给选择：单独谈心（加深羁绊，了解它过往/提振士气）/派它轮休（拉好感但暂缺战力）/放任（短期无关，埋隐患）。走 npc 心情链。",
     "reward_hint": "增进羁绊/士气，或埋情绪隐患",
     },
    {"kind": "event", "id": "curious_follower", "name": "尾随的小迷弟",
     "direction": "情感羁绊", "desc": "巡逻时你总觉得背后有人跟着——回头发现是只怯生生的小魔物，远远缀着你的队伍，眼里满是崇拜，却不敢靠近。",
     "gm_hook": "羁绊向。给选择：温和招手（引它入队，可能成忠诚追随者）/故意甩开（它默默记下你）/无视（它持续尾随）。走 npc 关系链。",
     "reward_hint": "潜在忠诚追随者",
     },
]


# ============================================================
# ✅ 探索分区（EXPLORE_ZONES）—— 2026-08-26 新增
# 分区 = 难度 × 主题 两维。玩家选一个区探索，区内产出按难度/主题分层。
# 「巡逻」玩法升级为「探索分区」，概率 30收集/30战斗/30招募/10其他。
#
# 难度三档（越难奖励越好）：
#   safe  安全   Lv1-3   基础掉落
#   danger 危险  Lv4-6   中档掉落
#   high   高危  Lv7-9   高档掉落（稀有装/强力魔物）
# 同难度下两个主题区风味不同（敌人/收集物/招募池各异）。
# ============================================================
EXPLORE_ZONES = [
    # ── 🟢 安全区（Lv1-3，基础）──
    {"id": "moss_cave", "name": "苔藓洞窟", "difficulty": "safe",
     "lvl_range": (1, 3), "theme": "温润苔藓", "risk": "安全",
     "desc": "入口垂着湿润的苔藓，洞壁渗着暖暖的地下水汽。低阶魔物在阴影里探头探脑。",
     "enemy_pool": [
         {"name": "苔藓蝙蝠", "species": "魔物", "level": 1,
          "stats": {"END":1,"STR":1,"SPD":3,"DEF":1,"INT":1,"MP":1,"WIL":1},
          "skills_raw": "噬咬:斩击:10+1.5×力量+0.5×速度:耐力8:2.5s"},
         {"name": "洞穴史莱姆", "species": "魔物", "level": 2,
          "stats": {"END":3,"STR":1,"SPD":1,"DEF":2,"INT":1,"MP":1,"WIL":1},
          "skills_raw": "腐蚀:刺击:9+1.0×智力:耐力6:3.0s"},
     ],
     "collect_pool": ["魔法苔藓", "地脉结晶", "湿滑菌菇"],
     "recruit_pool": ["史莱姆", "蝙蝠"],
     "reward_tier": "base",
     "gm_hook": "洞窟潮闷湿滑，敌人低阶。事件方向偏「克制/温和」，收集物是可食/可炼的低阶材料。",
    },
    {"id": "edge_forest", "name": "边境林地", "difficulty": "safe",
     "lvl_range": (1, 3), "theme": "自然生机", "risk": "安全",
     "desc": "地下城上方的林地上，藤蔓与光斑交织。温和的魔物在此栖居。",
     "enemy_pool": [
         {"name": "野兔魔", "species": "魔物", "level": 1,
          "stats": {"END":1,"STR":1,"SPD":4,"DEF":1,"INT":1,"MP":1,"WIL":1},
          "skills_raw": "蹬踢:钝击:11+1.0×速度+0.5×力量:耐力8:2.0s"},
         {"name": "树藤妖", "species": "魔物", "level": 2,
          "stats": {"END":3,"STR":2,"SPD":1,"DEF":2,"INT":1,"MP":1,"WIL":1},
          "skills_raw": "缠绕:刺击:10+1.0×智力:耐力7:3.0s"},
     ],
     "collect_pool": ["野莓", "树心木", "晨露"],
     "recruit_pool": ["野狼", "野猪"],
     "reward_tier": "base",
     "gm_hook": "林间有微风与鸟鸣。事件方向偏「自然/成长」，收集物是食物/木材类低阶资材。",
    },

    # ── 🟡 危险区（Lv4-6，中档）──
    {"id": "lava_mine", "name": "熔岩矿井", "difficulty": "danger",
     "lvl_range": (4, 6), "theme": "灼热矿脉", "risk": "危险",
     "desc": "废弃矿井里热浪翻滚，岩浆在矿槽间流淌，铁壁被烧得通红。",
     "enemy_pool": [
         {"name": "熔岩蜥", "species": "魔物", "level": 4,
          "stats": {"END":5,"STR":5,"SPD":2,"DEF":4,"INT":2,"MP":2,"WIL":3},
          "skills_raw": "喷焰:刺击:17+1.0×智力:耐力12:3.0s;尾扫:钝击:16+2.0×力量:耐力10:2.5s"},
         {"name": "火元素", "species": "魔物", "level": 5,
          "stats": {"END":4,"STR":4,"SPD":5,"DEF":2,"INT":4,"MP":4,"WIL":3},
          "skills_raw": "爆炎:刺击:20+1.5×智力:耐力14:3.5s"},
     ],
     "collect_pool": ["熔火铁锭", "红晶石", "硫磺块"],
     "recruit_pool": ["火蜥", "小炎魔"],
     "reward_tier": "mid",
     "gm_hook": "热浪灼人，铁质矿脉。事件方向偏「灼热/矿藏」，收集物是中档锻造/附魔材料。",
    },
    {"id": "sunken_tomb", "name": "沉没墓穴", "difficulty": "danger",
     "lvl_range": (4, 6), "theme": "秘辛古墓", "risk": "危险",
     "desc": "被水淹过的古墓群，石棺半沉，苔痕斑驳，弥漫着陈旧的死亡气息。",
     "enemy_pool": [
         {"name": "骷髅守卫", "species": "魔物", "level": 4,
          "stats": {"END":4,"STR":4,"SPD":3,"DEF":5,"INT":2,"MP":2,"WIL":3},
          "skills_raw": "骨刀:斩击:17+2.0×力量:耐力11:2.5s"},
         {"name": "墓穴妖灵", "species": "魔物", "level": 5,
          "stats": {"END":3,"STR":3,"SPD":5,"DEF":2,"INT":5,"MP":5,"WIL":4},
          "skills_raw": "夺命低语:精神:19+1.5×智力:耐力12:3.0s"},
     ],
     "collect_pool": ["古币", "墓穴符文", "亡者之尘"],
     "recruit_pool": ["亡灵", "僵仆"],
     "reward_tier": "mid",
     "gm_hook": "死寂阴冷，尘封历史。事件方向偏「秘辛/历史」，收集物是可解锁传承/冢宝的中档材料。",
    },

    # ── 🔴 高危区（Lv7-9，高档）──
    {"id": "abyss_rift", "name": "深渊裂谷", "difficulty": "high",
     "lvl_range": (7, 9), "theme": "虚空狂乱", "risk": "高危",
     "desc": "大地裂开一道通往深处的缝隙，虚空寒气上涌，耳边是失真的低语。",
     "enemy_pool": [
         {"name": "虚空猎犬", "species": "魔物", "level": 7,
          "stats": {"END":7,"STR":7,"SPD":7,"DEF":4,"INT":4,"MP":4,"WIL":5},
          "skills_raw": "虚空撕咬:斩击:26+2.5×力量+0.5×速度:耐力16:2.5s"},
         {"name": "裂隙凝视者", "species": "魔物", "level": 8,
          "stats": {"END":6,"STR":5,"SPD":5,"DEF":5,"INT":8,"MP":8,"WIL":6},
          "skills_raw": "失序凝视:精神:30+2.0×智力:耐力18:4.0s"},
     ],
     "collect_pool": ["虚空结晶", "深渊之角", "失序核心"],
     "recruit_pool": ["虚空幼龙", "深渊魔"],
     "reward_tier": "high",
     "gm_hook": "虚空低语，理智受扰。事件方向偏「狂乱/强敌」，收集物是高阶稀有材料与遗物。",
    },
    {"id": "sulfur_throne", "name": "硫磺王座", "difficulty": "high",
     "lvl_range": (7, 9), "theme": "恶魔王庭", "risk": "高危",
     "desc": "地底深处的恶魔王座殿，硫磺味刺鼻，罪影低语，仿佛有群魔在此集会。",
     "enemy_pool": [
         {"name": "硫磺魔将", "species": "魔物", "level": 7,
          "stats": {"END":9,"STR":8,"SPD":4,"DEF":7,"INT":4,"MP":4,"WIL":5},
          "skills_raw": "魔焰斩:斩击:28+2.5×力量:耐力16:3.0s"},
         {"name": "罪孽魅影", "species": "魔物", "level": 8,
          "stats": {"END":5,"STR":5,"SPD":8,"DEF":3,"INT":7,"MP":7,"WIL":7},
          "skills_raw": "罪罚鞭挞:精神:27+1.5×智力+0.5×速度:耐力14:2.5s"},
     ],
     "collect_pool": ["硫磺圣晶", "恶魔之心", "罪孽之火"],
     "recruit_pool": ["小恶魔", "恶魔侍从"],
     "reward_tier": "high",
     "gm_hook": "王庭气氛压抑，群魔环伺。事件方向偏「恶魔/高阶」，收集物是可锻造神装/召唤的高阶圣物。",
    },
]

# 分区难度标签（供前端/日志显示）
ZONE_DIFFICULTY_LABEL = {"safe": "安全", "danger": "危险", "high": "高危"}


def pick_zone(zone_id) -> dict:
    """按 id 取分区；找不到返回 None"""
    for z in EXPLORE_ZONES:
        if z["id"] == zone_id:
            return z
    return None


def get_active_characters(sess: dict) -> list:
    """取玩家当前出战编制的活跃魔物（若无，取全部角色）"""
    chars = sess.get("characters", [])
    if not chars:
        return []
    active = [c for c in chars if c.get("active")]
    return active if active else chars



def patrol_encounter_rule() -> Rule:
    """巡逻遭遇：85% 概率从预设事件池抽一条，保证巡逻不空转"""
    def condition(ctx):
        return '巡逻' in ctx.get('action', '')

    def effect(ctx, rng):
            evt = rng.choice(PATROL_EVENT_POOL)
            return Event(
                name="patrol_encounter",
                data={"kind": evt["kind"], "event_id": evt["id"],
                      "name": evt["name"], "desc": evt["desc"],
                      "direction": evt.get("direction", ""), "gm_hook": evt.get("gm_hook", ""),
                      "reward_hint": evt.get("reward_hint", ""),
                      "enemy": evt.get("enemy")},
            )

    return Rule(
        name="巡逻遭遇",
        condition=condition,
        probability=0.85,
        effect=effect,
        description="巡逻时 85% 从预设事件池抽一条遭遇事件，防止空转",
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
