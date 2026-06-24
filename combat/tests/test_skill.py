"""技能解析测试 (匹配实际 API)"""
import pytest
from combat.skill import parse_tavern_skill, parse_tavern_skills, fighter_from_tavern_char


class TestParseTavernSkill:
    """注意: parse_tavern_skill 将中文类型映射为英文!"""

    def test_basic_skill(self):
        raw = "利爪:斩击:30+2.0×力量+1.5×速度:耐力22:3.5s"
        skill = parse_tavern_skill(raw)
        assert skill is not None
        assert skill["name"] == "利爪"
        assert skill["type"] == "slash"  # 斩击→slash
        assert "30" in skill["formula"]
        assert skill["stamina_cost"] == 22
        assert skill["cooldown"] == pytest.approx(3.5)

    def test_skill_with_mana(self):
        raw = "火球:法术:20+3.0×智力:蓝15:5.0s"
        skill = parse_tavern_skill(raw)
        assert skill["name"] == "火球"
        assert skill["type"] == "spirit"  # 法术→spirit
        assert skill["mana_cost"] == 15
        assert skill["stamina_cost"] == 0

    def test_skill_mixed_cost(self):
        raw = "龙息:斩击:40+2.0×精神:耐力10+蓝20:8.0s"
        skill = parse_tavern_skill(raw)
        assert skill["stamina_cost"] == 10
        assert skill["mana_cost"] == 20

    def test_skill_no_cost(self):
        raw = "应急爪击:斩击:10+1.0×力量::2.0s"
        skill = parse_tavern_skill(raw)
        assert skill is not None
        assert skill["stamina_cost"] == 0
        assert skill["mana_cost"] == 0

    def test_skill_default_interval(self):
        raw = "挥砍:斩击:15+2.0×力量:耐力14"
        skill = parse_tavern_skill(raw)
        assert skill["cooldown"] == pytest.approx(3.0)

    def test_invalid_format(self):
        assert parse_tavern_skill("单字段") is None
        assert parse_tavern_skill("只有:两个") is None
        assert parse_tavern_skill("") is None

    def test_type_mapping(self):
        """中文类型 → 英文映射"""
        cases = [
            ("利爪:斩击:30:耐力10:3s", "slash"),
            ("突刺:刺击:20:耐力8:2s", "pierce"),
            ("盾击:钝击:15:耐力12:4s", "blunt"),
            ("精神波:精神:20:蓝15:4s", "spirit"),
            ("铁壁:防御:0:耐力5:0.5s", "defense"),
        ]
        for raw, expected in cases:
            skill = parse_tavern_skill(raw)
            assert skill["type"] == expected, f"{raw} → expected {expected}, got {skill['type']}"

    def test_unknown_type_defaults_to_slash(self):
        skill = parse_tavern_skill("怪技:未知类型:10:耐力5:3s")
        assert skill["type"] == "slash"  # 未知类型默认 slash


class TestParseTavernSkills:
    """parse_tavern_skills 只接受分号分隔的字符串"""

    def test_multiple_skills_semicolon(self):
        raw = "挥砍:斩击:15+2.0×力量:耐力14:3.0s;突刺:刺击:18+2.0×速度:耐力12:2.5s;格挡:防御:0:耐力5:0.5s"
        skills = parse_tavern_skills(raw)
        assert len(skills) == 3

    def test_newline_separated(self):
        """换行分隔也支持（";" 分隔）"""
        raw = "挥砍:斩击:15:耐14:3s;突刺:刺击:18:耐12:2.5s"
        skills = parse_tavern_skills(raw)
        assert len(skills) == 2

    def test_empty_string(self):
        assert parse_tavern_skills("") == []

    def test_partially_invalid(self):
        raw = "挥砍:斩击:15:耐力14:3.0s;破格式;突刺:刺击:18:耐力12:2.5s"
        skills = parse_tavern_skills(raw)
        assert len(skills) == 2  # 无效的被过滤

    def test_single_skill_no_semicolon(self):
        raw = "挥砍:斩击:15+2.0×力量:耐力14:3.0s"
        skills = parse_tavern_skills(raw)
        assert len(skills) == 1


class TestFighterFromTavernChar:
    def test_basic_conversion(self):
        char = {
            "id": "cat_001", "name": "猫龙", "species": "猫龙", "level": 3,
            "stats": {"END": 5, "STR": 7, "SPD": 6, "DEF": 3, "INT": 2, "MP": 2, "WIL": 4},
            "skills": [
                {"name": "利爪", "type": "slash", "formula": "30+2.0*STR+1.5*SPD",
                 "stamina_cost": 22, "cooldown": 3.5},
                {"name": "格挡", "type": "defense", "formula": "50+5.0*DEF",
                 "stamina_cost": 5, "cooldown": 0.5},
            ],
            "equipment": {},
        }
        cfg = fighter_from_tavern_char(char, team=0)
        assert cfg["name"] == "猫龙"
        assert cfg["level"] == 3
        assert cfg["STR"] == 7
        assert len(cfg.get("skills", [])) >= 2

    def test_empty_skills_returns_empty(self):
        """fighter_from_tavern_char 不会自动添加技能——由调用方负责"""
        char = {
            "id": "test_1", "name": "测试", "species": "人类", "level": 1,
            "stats": {"END": 4, "STR": 4, "SPD": 4, "DEF": 2, "INT": 1, "MP": 1, "WIL": 3},
            "skills": [],
        }
        cfg = fighter_from_tavern_char(char, team=0, equipment_pool=[])
        skills = cfg.get("skills", [])
        # 空技能列表就是空——调用方（server.py）负责补格挡
        assert len(skills) == 0

    def test_with_equipment_attribute_bonus(self):
        """装备属性加成在 attribute_bonus 字段"""
        char = {
            "id": "test_2", "name": "装备测试", "species": "人类", "level": 1,
            "stats": {"END": 4, "STR": 4, "SPD": 4, "DEF": 2, "INT": 1, "MP": 1, "WIL": 3},
            "skills": [],
            "equipment": {"weapon": "rusty_sword", "armor": "leather_vest"},
        }
        pool = [
            {"id": "rusty_sword", "name": "生锈短剑", "stats_bonus": {"STR": 2}},
            {"id": "leather_vest", "name": "破布衣", "stats_bonus": {"护甲": 100}},
        ]
        cfg = fighter_from_tavern_char(char, team=0, equipment_pool=pool)
        bonus = cfg.get("equipment_bonus", {})
        assert bonus.get("STR", 0) == 2

    def test_equipment_skills_injected(self):
        char = {
            "id": "test_3", "name": "法杖测试", "species": "人类", "level": 1,
            "stats": {"END": 4, "STR": 3, "SPD": 4, "DEF": 2, "INT": 5, "MP": 5, "WIL": 3},
            "skills": [],
            "equipment": {"weapon": "fire_staff"},
        }
        pool = [
            {"id": "fire_staff", "name": "炎之杖", "stats_bonus": {"INT": 2},
             "skill": {"name": "火球术", "type": "fire", "formula": "25+3.0*INT",
                       "stamina_cost": 0, "mana_cost": 15, "cooldown": 5.0}},
        ]
        cfg = fighter_from_tavern_char(char, team=0, equipment_pool=pool)
        skills = cfg.get("skills", [])
        skill_names = [s["name"] for s in skills]
        assert "火球术" in skill_names
