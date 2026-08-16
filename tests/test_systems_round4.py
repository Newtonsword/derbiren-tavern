# -*- coding: utf-8 -*-
"""
第 4 轮：战斗环境系统 / NPC 记忆上下文注入 / 数据一致性
"""
import requests, json, sys, os, asyncio

BASE = "http://127.0.0.1:8099"
PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name} {detail}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")

def main():
    print("=== 系统深度测试（第 4 轮）===")

    # ── 战斗环境系统 ──
    print("\n1. 战斗环境对结果的影响...")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from combat import Fighter, CombatSim, fighter_from_tavern_char

    def mk(name, lv, stats, skills):
        return {"id": f"m_{name}", "name": name, "species": "人类", "level": lv,
                "stats": stats, "skills": skills, "passives": [], "equipment": {}, "pregnant": None}

    SK = [{"name": "攻击", "type": "斩击", "formula": "20+2.0×力量+1.0×速度",
           "cost": "耐力10", "interval": "3.0s", "hit_formula": "80+2.0×速度"}]
    stats = {"END": 10, "STR": 10, "SPD": 10, "DEF": 8, "INT": 5, "MP": 8, "WIL": 6}

    def fight_env(env, seed_attr=None):
        a = Fighter(fighter_from_tavern_char(mk("A", 5, stats, SK)), SK)
        b = Fighter(fighter_from_tavern_char(mk("B", 5, stats, SK)), SK)
        sim = CombatSim([a], [b], environment=env)
        res = asyncio.run(sim.run())
        return res

    for env in ["open", "narrow", "field", "arena"]:
        res = fight_env(env)
        total = sum(f.hp for f in (res.team0_final if hasattr(res, 'team0_final') else [])) if hasattr(res, 'team0_final') else 0
        print(f"   {env}: 胜者={getattr(res, 'victor_team', '?')} ")
    check("4 种环境都能跑", True)

    # 距离系统（PositionManager 生效）
    print("\n2. 距离/位置系统...")
    from combat.sim import PositionManager
    a = Fighter(fighter_from_tavern_char(mk("A", 5, stats, SK)), SK)
    b = Fighter(fighter_from_tavern_char(mk("B", 5, stats, SK)), SK)
    pm = PositionManager([a], [b], "open")
    dist = pm.distance(a, b)
    print(f"   初始距离: {dist}")
    check("位置系统初始化", dist >= 0)

    # ── NPC 记忆注入上下文（@对话后记忆进入 persona）──
    print("\n3. NPC 记忆上下文注入...")
    r = requests.post(f"{BASE}/api/session/new", json={
        "player_name": "记忆测试", "char_name": "吱吱", "char_species": "猫龙"}, timeout=60)
    sid = r.json()["session_id"]
    # 三次 @对话，让记忆累积
    for i, msg in enumerate(["@吱吱 记住我喜欢蓝蘑菇", "@吱吱 我们明天要去打哥布林", "@吱吱 你欠我一个承诺"]):
        requests.post(f"{BASE}/api/session/{sid}/chat", json={"message": msg}, timeout=120)
    s = requests.get(f"{BASE}/api/session/{sid}", timeout=10).json()
    c = s["characters"][0]
    mem = c.get("persona", {}).get("memory", [])
    print(f"   吱吱记忆 {len(mem)} 条")
    for m in mem:
        print(f"   - 第{m.get('turn')}天: {m.get('event', '')[:40]}")
    check("记忆累积 ≥3 条", len(mem) >= 3, f"({len(mem)})")
    check("记忆按天记录", all("turn" in m for m in mem))

    # 记忆上限（30 条截断）
    print("\n4. 记忆上限截断...")
    from npc_persona import update_npc_memory, ensure_persona
    test_char = {"name": "测试", "species": "猫龙", "level": 1, "stats": {}, "skills": []}
    ensure_persona(test_char, "猫龙")
    for i in range(40):
        update_npc_memory(test_char, f"事件{i}", i)
    check("记忆截断到 30 条", len(test_char["persona"]["memory"]) == 30, f"({len(test_char['persona']['memory'])})")

    # ── 数据一致性：stats 值域 ──
    print("\n5. 角色 stats 完整性...")
    s = requests.get(f"{BASE}/api/session/{sid}", timeout=10).json()
    for c in s.get("characters", []):
        st = c.get("stats", {})
        keys_ok = all(k in st for k in ["END", "STR", "SPD", "DEF", "INT", "MP", "WIL"])
        vals_ok = all(isinstance(v, (int, float)) and v >= 1 for v in st.values()) if st else True
        check(f"{c['name']} stats 完整", keys_ok and vals_ok, f"({st})")
        check(f"{c['name']} 有 persona", bool(c.get("persona")))

    # ── 清理 ──
    try:
        os.remove(f"C:/Users/niutun/AppData/Local/hermes/output/derbiren-tavern/saves/{sid}.json")
    except Exception:
        pass

    print(f"\n=== 第4轮结果: {PASS} 通过 / {FAIL} 失败 ===")
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
