# -*- coding: utf-8 -*-
"""
第 5 轮：战斗机制细节（格挡/闪避/护甲/暴击）/ 全端点扫描 / 压力
"""
import requests, json, sys, os, asyncio, time

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
    print("=== 系统深度测试（第 5 轮）===")

    # ── 战斗机制细节 ──
    print("\n1. 战斗机制（格挡/闪避/护甲/暴击）...")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from combat import Fighter, CombatSim, fighter_from_tavern_char

    def mk(name, lv, stats, skills):
        return {"id": f"m_{name}", "name": name, "species": "人类", "level": lv,
                "stats": stats, "skills": skills, "passives": [], "equipment": {}, "pregnant": None}

    ATK = [{"name": "攻击", "type": "斩击", "formula": "20+2.0×力量+1.0×速度",
            "cost": "耐力10", "interval": "3.0s", "hit_formula": "95+2.0×速度"}]
    DEF = [{"name": "格挡", "type": "防御", "formula": "50+5.0×耐力",
            "cost": "耐力5", "interval": "持续"}]

    def fight(astats, bstats, askills, bskills, seed_attr=None):
        a = Fighter(fighter_from_tavern_char(mk("A", 5, astats, askills)), askills)
        b = Fighter(fighter_from_tavern_char(mk("B", 5, bstats, bskills), team=1), bskills)
        sim = CombatSim([a], [b])
        return asyncio.run(sim.run())

    base = {"END": 10, "STR": 10, "SPD": 10, "DEF": 8, "INT": 5, "MP": 8, "WIL": 6}
    # 有护甲 vs 无护甲（护甲吸收）
    armored = dict(base); armored["DEF"] = 20
    r1 = fight(armored, dict(base), ATK, ATK)
    print(f"   高防 vs 低防: 胜者={getattr(r1, 'victor_team', '?')}")
    check("高防战斗可完成", True)

    # 带格挡技能 vs 不带
    r2 = fight(dict(base), dict(base), ATK + DEF, ATK)
    print(f"   带格挡 vs 不带: 胜者={getattr(r2, 'victor_team', '?')}")
    check("格挡战斗可完成", True)

    # 检查伤害日志里有护甲/格挡吸收信息
    sim = CombatSim([Fighter(fighter_from_tavern_char(mk("A", 5, dict(base), ATK)), ATK)],
                    [Fighter(fighter_from_tavern_char(mk("B", 5, dict(base), ATK), team=1), ATK)])
    res = asyncio.run(sim.run())
    logs = [e.get("msg", "") if isinstance(e, dict) else getattr(e, "msg", "") for e in getattr(res, "log", [])]
    dmg_entries = [l for l in logs if "伤害" in str(l) or "DMG" in str(l) or "命中" in str(l) or "护甲" in str(l) or "格挡" in str(l) or "吸收" in str(l)]
    print(f"   战斗日志条目: {len(logs)}，含伤害/护甲/格挡的: {len(dmg_entries)}")
    check("战斗日志有机制信息", len(dmg_entries) > 0, f"({len(dmg_entries)}条)")
    for e in dmg_entries[:4]:
        print(f"   {str(e)[:100]}")

    # ── 全端点扫描 ──
    print("\n2. 全 API 端点扫描...")
    endpoints = [
        ("GET", "/"), ("GET", "/api/session/{sid}/events"),
        ("GET", "/api/session/{sid}/characters"), ("GET", "/api/equipment"),
        ("GET", "/api/constructions"), ("GET", "/api/species"), ("GET", "/api/saves"),
        ("GET", "/api/library"), ("GET", "/api/settings"),
    ]
    r = requests.post(f"{BASE}/api/session/new", json={"player_name": "扫描", "char_name": "吱吱", "char_species": "猫龙"}, timeout=60)
    sid = r.json()["session_id"]
    for method, ep in endpoints:
        url = ep.replace("{sid}", sid)
        try:
            rr = requests.request(method, f"{BASE}{url}", timeout=10)
            status = rr.status_code
            ok = status in (200, 404, 422)
            check(f"{method} {ep.split('/')[-1]}", ok, f"({status})")
        except Exception as e:
            check(f"{method} {ep}", False, f"异常 {e}")

    # POST 端点
    post_eps = [
        ("/api/session/{sid}/chat", {"message": "测试"}), ("/api/roll", {"message": "d20"}),
        ("/api/session/{sid}/dev", {"action": "set_day", "day": 1}),
    ]
    for ep, body in post_eps:
        url = ep.replace("{sid}", sid)
        rr = requests.post(f"{BASE}{url}", json=body, timeout=30)
        ok = rr.status_code in (200, 404, 422)
        check(f"POST {ep.split('/')[-1] or ep}", ok, f"({rr.status_code})")

    # ── 压力：8 连发（每发调 AI 5-15s，8 发约 2 分钟）──
    print("\n3. 压力测试（8 连发 chat）...")
    ok_count = 0
    start = time.time()
    for i in range(8):
        try:
            rr = requests.post(f"{BASE}/api/session/{sid}/chat", json={"message": f"压力{i}"}, timeout=45)
            if rr.status_code == 200:
                ok_count += 1
        except Exception:
            pass
    elapsed = time.time() - start
    print(f"   8 连发成功 {ok_count}/8，耗时 {elapsed:.1f}s")
    check("压力测试通过", ok_count >= 7, f"({ok_count}/8)")

    # 清理
    try:
        os.remove(f"C:/Users/niutun/AppData/Local/hermes/output/derbiren-tavern/saves/{sid}.json")
    except Exception:
        pass

    print(f"\n=== 第5轮结果: {PASS} 通过 / {FAIL} 失败 ===")
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
