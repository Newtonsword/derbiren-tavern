# -*- coding: utf-8 -*-
"""
P0 深化测试：NPC 独立心智 + 世界权限模型
运行：python -m pytest tests/test_p0_deepen.py -q
"""
import os, sys, re, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import npc_persona as npc

# ── P0-1 NPC 独立心智 ──

def test_ensure_persona_creates_fields():
    char = {"name": "吱吱", "species": "猫龙", "level": 3, "stats": {}, "skills": []}
    p = npc.ensure_persona(char, "猫龙")
    assert set(p.keys()) >= {"personality", "memory", "goal", "secret", "mood", "relationship"}
    assert "傲娇" in p["personality"]  # 猫龙性格倾向

def test_ensure_persona_random_species():
    char = {"name": "无名", "species": "未知物种", "level": 1, "stats": {}, "skills": []}
    p = npc.ensure_persona(char, "未知物种")
    assert p["personality"]  # 有性格

def test_extract_npc_target():
    assert npc.extract_npc_target("你好 @吱吱 今天咋样") == "吱吱"
    assert npc.extract_npc_target("随便聊聊") is None
    assert npc.extract_npc_target("@猫龙 过来") == "猫龙"

def test_find_char_by_name():
    chars = [{"name": "吱吱"}, {"name": " 嘎嘎 "}]
    assert npc.find_char_by_name(chars, "吱吱") is not None
    assert npc.find_char_by_name(chars, "嘎嘎") is not None
    assert npc.find_char_by_name(chars, "不存在") is None

def test_build_npc_system_prompt():
    char = {"name": "吱吱", "species": "猫龙", "level": 5,
            "stats": {"END": 5, "STR": 6}, "skills": [{"name": "利爪"}]}
    p = npc.build_npc_system_prompt(char, "地下城世界观", 10)
    assert "吱吱" in p
    assert "你不是 GM" in p
    assert "你的秘密" in p
    assert "绝对" in p  # 不能改数据规则

def test_update_npc_memory_and_mood():
    char = {"name": "吱吱", "species": "猫龙", "level": 1, "stats": {}, "skills": []}
    npc.ensure_persona(char, "猫龙")
    npc.update_npc_memory(char, "魔王夸了我", 5)
    npc.update_npc_mood(char, "高兴")
    assert char["persona"]["memory"][0]["event"] == "魔王夸了我"
    assert char["persona"]["mood"] == "高兴"

def test_personas_to_context():
    chars = [{"name": "吱吱", "species": "猫龙", "level": 1, "stats": {}, "skills": []},
             {"name": "嘎嘎", "species": "史莱姆", "level": 1, "stats": {}, "skills": []}]
    ctx = npc.personas_to_context(chars)
    assert "吱吱" in ctx and "嘎嘎" in ctx

# ── P0-2 世界权限模型（引擎裁决）──

def _load_server_src():
    """从 server.py 源码中提取裁决逻辑（避免 import 整个 FastAPI app）"""
    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server.py")
    with open(src_path, encoding="utf-8") as f:
        return f.read()

def test_server_has_adjudicate():
    src = _load_server_src()
    assert "def _engine_adjudicate" in src
    assert "def _inject_propose_notes" in src
    assert "PROPOSE_CHANGE_RE" in src
    assert "FORBIDDEN_PROPOSE_TERMS" in src
    assert "ALLOWED_PROPOSE_TYPES" in src

def test_server_chat_calls_adjudicate():
    src = _load_server_src()
    assert "reply, propose_notes = _engine_adjudicate(reply)" in src
    assert "stored_reply = _inject_propose_notes(clean_reply, propose_notes)" in src

def test_server_sys_has_permission_rules():
    src = _load_server_src()
    assert "世界权限铁律" in src  # SYS 提示词权限规则
    assert "PROPOSE_CHANGE" in src

def test_server_npc_integration():
    src = _load_server_src()
    assert "from npc_persona import" in src
    assert "ensure_persona(c, species)" in src  # _make_char 初始化
    assert "extract_npc_target(req.message)" in src  # chat 中 NPC 切换
    assert "personas_to_context(chars)" in src  # GM 上下文注入

# 模拟裁决逻辑（与 server.py 一致，防回归）
PROPOSE_CHANGE_RE = re.compile(r'\[PROPOSE_CHANGE:\s*(.+?)\s*\]', re.IGNORECASE)
FORBIDDEN = ['hp', '血量', '生命', '背包', '金币', '删除角色', '直接加属性']
ALLOWED = [('招募', 'CHAR_ADD'), ('升级', 'LEVEL_UP'), ('改名', 'CHAR_RENAME'), ('蓝图', 'CONSTRUCTION')]

def _mock_adjudicate(reply):
    if '[PROPOSE_CHANGE:' not in reply:
        return reply, []
    notes = []
    for m in PROPOSE_CHANGE_RE.finditer(reply):
        raw = m.group(1).strip()
        raw_l = raw.lower()
        if any(t in raw_l for t in FORBIDDEN):
            notes.append(('deny', raw))
        elif any(kw in raw for kw, _ in ALLOWED):
            notes.append(('allow', raw))
        else:
            notes.append(('deny', raw))
    return PROPOSE_CHANGE_RE.sub('', reply), notes

def test_adjudicate_allow():
    r, n = _mock_adjudicate("一只魔物来了 [PROPOSE_CHANGE: 招募一只新魔物 猫龙]")
    assert any(v == 'allow' for v, _ in n)
    assert "[PROPOSE_CHANGE" not in r  # 标签被移除

def test_adjudicate_deny_hp():
    r, n = _mock_adjudicate("[PROPOSE_CHANGE: 把玩家HP改成满]")
    assert any(v == 'deny' for v, _ in n)

def test_adjudicate_deny_unknown():
    r, n = _mock_adjudicate("[PROPOSE_CHANGE: 把天气变成雨天]")
    assert any(v == 'deny' for v, _ in n)

def test_adjudicate_no_propose():
    r, n = _mock_adjudicate("正常叙述")
    assert n == []
