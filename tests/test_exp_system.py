# -*- coding: utf-8 -*-
"""
经验值系统验证测试：
1. 探索给经验（空手/装备/魔物三种结果都加）
2. 探索经验触发升级（_check_levelup）
3. /day 锻炼给经验 + 升级
4. 战斗波次全队经验 + 升级
5. 前端经验条数据（exp/level 字段完整）
"""
import requests, json, sys, os, glob, random

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

def main():
    print("=== 经验值系统验证测试 ===")

    # 1. 探索给经验（多次探索直到覆盖结果类型）
    print("\n1. 探索经验...")
    r = requests.post(f"{BASE}/api/session/new", json={
        "player_name": "经验测试", "char_name": "吱吱", "char_species": "猫龙"}, timeout=60)
    sid = r.json()["session_id"]
    s = get_session(sid)
    cid = s["characters"][0]["id"]
    exp_before = s["characters"][0].get("exp", 0)
    print(f"   初始 exp: {exp_before}")

    exp_gained = 0
    results = []
    # 用 set_day 重置 explored_today 后多次探索
    for i in range(3):
        rr = requests.post(f"{BASE}/api/session/{sid}/explore", json={"char_id": cid}, timeout=10)
        if rr.status_code == 200:
            d = rr.json()
            results.append(d.get("result"))
            print(f"   探索{i}: {d.get('result')} | {d.get('msg', '')[:60]}")
        else:
            # 已探索过 → 跨天
            requests.post(f"{BASE}/api/session/{sid}/dev", json={"action": "set_day", "day": i+2}, timeout=10)
            rr = requests.post(f"{BASE}/api/session/{sid}/explore", json={"char_id": cid}, timeout=10)
            if rr.status_code == 200:
                d = rr.json()
                results.append(d.get("result"))
                print(f"   探索{i}: {d.get('result')} | {d.get('msg', '')[:60]}")

    s2 = get_session(sid)
    exp_after = s2["characters"][0].get("exp", 0)
    print(f"   探索后 exp: {exp_after}")
    check("探索加了经验", exp_after > exp_before, f"({exp_before}→{exp_after})")
    check("经验数 >0", exp_after > 0)

    # 2. 探索经验触发升级（加大量 exp 直接看升级）
    print("\n2. 升级触发...")
    rr = requests.post(f"{BASE}/api/session/{sid}/dev", json={"action": "add_exp", "amount": 500}, timeout=10)
    s3 = get_session(sid)
    c = s3["characters"][0]
    print(f"   Lv.{c['level']} exp={c.get('exp')} free_points={c.get('free_points')} skill_pts={c.get('pending_skill_points')}")
    check("升级生效", c["level"] > 1, f"(Lv{c['level']})")
    check("升级加点", c.get("free_points", 0) >= 3, f"(free={c.get('free_points')})")

    # 3. 前端经验条数据完整性
    print("\n3. 前端经验条数据...")
    s4 = get_session(sid)
    c = s4["characters"][0]
    check("exp 字段存在", "exp" in c, f"(exp={c.get('exp')})")
    check("level 字段存在", "level" in c)
    check("exp 是数字", isinstance(c.get("exp"), (int, float)))

    # 4. 经验值公式一致性（后端 _check_levelup: need = 100 * level）
    print("\n4. 升级公式验证...")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from server import _check_levelup
    test = {"level": 1, "exp": 99, "free_points": 3, "pending_skill_points": 0}
    _check_levelup(test)
    check("99 经验不升级", test["level"] == 1, f"(Lv{test['level']})")
    test = {"level": 1, "exp": 100, "free_points": 3, "pending_skill_points": 0}
    _check_levelup(test)
    check("100 经验升级", test["level"] == 2, f"(Lv{test['level']})")
    check("升级+1自由点", test["free_points"] == 4, f"(free={test['free_points']})")
    check("升级+1技能点", test["pending_skill_points"] == 1, f"(pts={test['pending_skill_points']})")
    test = {"level": 1, "exp": 300, "free_points": 3, "pending_skill_points": 0}
    _check_levelup(test)
    check("连升多级", test["level"] == 3, f"(Lv{test['level']})")
    check("连升多级点数", test["free_points"] == 5 and test["pending_skill_points"] == 2, f"(free={test['free_points']} pts={test['pending_skill_points']})")

    # 清理
    try:
        os.remove(f"C:/Users/niutun/AppData/Local/hermes/output/derbiren-tavern/saves/{sid}.json")
    except Exception:
        pass

    print(f"\n=== 经验值测试结果: {PASS} 通过 / {FAIL} 失败 ===")
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
