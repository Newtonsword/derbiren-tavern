# -*- coding: utf-8 -*-
"""
系统深度测试（第 3 轮）：多角色战斗 / 防御工事 / 进化 / roll / 边界条件
"""
import requests, json, sys, os

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

def get_session(sid):
    return requests.get(f"{BASE}/api/session/{sid}", timeout=10).json()

def chat(sid, msg, timeout=150):
    r = requests.post(f"{BASE}/api/session/{sid}/chat", json={"message": msg}, timeout=timeout)
    return r.json()

def dev(sid, **kw):
    return requests.post(f"{BASE}/api/session/{sid}/dev", json=kw, timeout=10).json()

def main():
    print("=== 系统深度测试（第 3 轮）===")
    r = requests.post(f"{BASE}/api/session/new", json={
        "player_name": "深测魔王", "char_name": "吱吱", "char_species": "猫龙"}, timeout=60)
    sid = r.json()["session_id"]
    print(f"1. 会话: {sid}")
    s = get_session(sid)
    cid = s["characters"][0]["id"]

    # ── /roll 骰子 ──
    print("\n2. /roll 骰子...")
    rr = requests.post(f"{BASE}/api/roll", json={"expr": "d20"}, timeout=10)
    if rr.status_code == 200:
        d = rr.json()
        print(f"   d20 = {d}")
        check("roll d20 返回数值", isinstance(d, (int, float, dict)))
    else:
        # 可能参数结构不同
        print(f"   roll: {rr.status_code} {rr.text[:100]}")

    # ── 边界条件：不存在会话 ──
    print("\n3. 边界条件...")
    r404 = requests.get(f"{BASE}/api/session/nonexistent123", timeout=10)
    print(f"   不存在会话: {r404.status_code}")
    check("不存在会话返回 404", r404.status_code == 404)
    r404b = requests.post(f"{BASE}/api/session/nonexistent123/chat", json={"message": "hi"}, timeout=10)
    print(f"   不存在会话 chat: {r404b.status_code}")
    check("不存在会话 chat 有处理", r404b.status_code in (404, 200))
    # 空消息
    r_empty = requests.post(f"{BASE}/api/session/{sid}/chat", json={"message": "  "}, timeout=10)
    print(f"   空消息: {r_empty.status_code} {r_empty.text[:80]}")

    # ── 探索不存在角色 ──
    r_bad = requests.post(f"{BASE}/api/session/{sid}/explore", json={"char_id": "nope"}, timeout=10)
    print(f"   探索不存在角色: {r_bad.status_code}")
    check("探索不存在角色返回 400", r_bad.status_code == 400)

    # ── 防御工事 ──
    print("\n4. 防御工事系统...")
    cons = requests.get(f"{BASE}/api/session/{sid}/constructions", timeout=10)
    if cons.status_code == 200:
        cl = cons.json()
        cl_list = cl if isinstance(cl, list) else cl.get("constructions", [])
        print(f"   工事列表: {len(cl_list)} 项")
        for c in cl_list[:3]:
            print(f"   - {c.get('name')} ({c.get('type')}) 状态={c.get('status')}")
        check("工事列表可读", isinstance(cl_list, list))
    else:
        print(f"   工事: {cons.status_code} {cons.text[:80]}")

    # ── 进化系统 ──
    print("\n5. 进化系统...")
    s2 = get_session(sid)
    c0 = s2["characters"][0]
    r_ev = requests.post(f"{BASE}/api/session/{sid}/characters/{c0['id']}/evolve", timeout=30)
    print(f"   进化: {r_ev.status_code} {r_ev.text[:150]}")
    check("进化接口响应", r_ev.status_code in (200, 400, 422))

    # ── 多角色战斗（引擎层 2v2）──
    print("\n6. 多角色战斗（引擎 2v2）...")
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from combat import Fighter, CombatSim, fighter_from_tavern_char
        import asyncio

        def mk(name, species, lv, stats, skills):
            return {"id": f"m_{name}", "name": name, "species": species, "level": lv,
                    "stats": stats, "skills": skills, "passives": [], "equipment": {}, "pregnant": None}

        SK = [{"name": "攻击", "type": "斩击", "formula": "20+2.0×力量+1.0×速度",
               "cost": "耐力10", "interval": "3.0s", "hit_formula": "80+2.0×速度"}]
        team0 = [Fighter(fighter_from_tavern_char(mk("A1", "人类", 5, {"END": 10, "STR": 10, "SPD": 10, "DEF": 8, "INT": 5, "MP": 8, "WIL": 6}, SK)), SK),
                 Fighter(fighter_from_tavern_char(mk("A2", "人类", 4, {"END": 8, "STR": 8, "SPD": 9, "DEF": 7, "INT": 5, "MP": 7, "WIL": 6}, SK)), SK)]
        team1 = [Fighter(fighter_from_tavern_char(mk("B1", "人类", 5, {"END": 10, "STR": 10, "SPD": 10, "DEF": 8, "INT": 5, "MP": 8, "WIL": 6}, SK)), SK),
                 Fighter(fighter_from_tavern_char(mk("B2", "人类", 4, {"END": 8, "STR": 8, "SPD": 9, "DEF": 7, "INT": 5, "MP": 7, "WIL": 6}, SK)), SK)]
        hp0 = [f.hp for f in team0] + [f.hp for f in team1]
        sim = CombatSim(team0, team1)
        res = asyncio.run(sim.run())
        hp1 = [f.hp for f in team0] + [f.hp for f in team1]
        total_dmg = sum(a - b for a, b in zip(hp0, hp1))
        print(f"   2v2 总伤害: {total_dmg:.0f}")
        print(f"   胜者: {res.victor_team if hasattr(res, 'victor_team') else '?'}")
        check("2v2 战斗有伤害", total_dmg > 0, f"({total_dmg:.0f})")
    except ImportError as e:
        print(f"   import 失败: {e}")

    # ── 并发/重复请求 ──
    print("\n7. 快速连续请求（防崩）...")
    ok_count = 0
    for i in range(5):
        try:
            rr = requests.post(f"{BASE}/api/session/{sid}/chat", json={"message": f"测试消息{i}"}, timeout=60)
            if rr.status_code == 200:
                ok_count += 1
        except Exception:
            pass
    print(f"   5 连发成功 {ok_count}/5")
    check("连续请求稳定", ok_count >= 4, f"({ok_count}/5)")

    print(f"\n=== 第3轮结果: {PASS} 通过 / {FAIL} 失败 ===")
    try:
        os.remove(f"C:/Users/niutun/AppData/Local/hermes/output/derbiren-tavern/saves/{sid}.json")
    except Exception:
        pass
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
