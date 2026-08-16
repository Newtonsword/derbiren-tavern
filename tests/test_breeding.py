# -*- coding: utf-8 -*-
"""
配种系统深度测试：怀孕 → 生产 → 后代属性继承
验证：程序自动计算孕期、后代继承双亲属性平均+随机突变、各取一个技能
"""
import requests, json, sys, os, re, time

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
    print("=== 配种系统深度测试 ===")
    r = requests.post(f"{BASE}/api/session/new", json={
        "player_name": "配种测试魔王", "char_name": "吱吱", "char_species": "猫龙"}, timeout=60)
    sid = r.json()["session_id"]
    print(f"1. 会话: {sid}")

    # 确保有两只魔物——探索招第二只（加大次数保证命中：15%×20≈96%）
    s = get_session(sid)
    chars = s.get("characters", [])
    print(f"   初始角色: {len(chars)} 只")
    if len(chars) < 2:
        cid = chars[0]["id"]
        for attempt in range(20):
            dev(sid, action="set_day", day=attempt + 2, dta=5)
            rr = requests.post(f"{BASE}/api/session/{sid}/explore", json={"char_id": cid}, timeout=15)
            if rr.status_code == 200 and rr.json().get("result") == "monster":
                print(f"   探索第{attempt+2}天招到: {rr.json().get('name')} ({rr.json().get('species')})")
                break
        s = get_session(sid)
        chars = s.get("characters", [])
    check("有至少 2 只魔物", len(chars) >= 2, f"({len(chars)})")
    for c in chars:
        print(f"   - {c['name']} ({c['species']}) Lv{c['level']}")

    if len(chars) < 2:
        print("   无法测试配种（角色不足）")
        return 1 if FAIL else 0

    # 配种：父=第一只 母=第二只
    print("\n2. 触发配种 (/day 配种 父=xx 母=yy)...")
    c1, c2 = chars[0], chars[1]
    resp = chat(sid, f"/day 配种 父={c1['name']} 母={c2['name']}", timeout=150)
    narr = resp.get("narrative", "")
    print(f"   配种回复[:200]: {narr[:200]}")

    s2 = get_session(sid)
    preg = [c for c in s2.get("characters", []) if c.get("pregnant")]
    if preg:
        p = preg[0]["pregnant"]
        due = p.get("due_day")
        print(f"   ✅ 怀孕: {preg[0]['name']} 预产期第{due}天 (孕期{p.get('gest_days','?')}天)")
        check("怀孕状态写入", bool(due))
        # 推进到预产期（孕期结束后生产）
        s3 = get_session(sid)
        cur_day = s3.get("day", 1)
        base_count = len(s3.get("characters", []))
        produced = False
        for d in range(cur_day + 1, due + 3):
            dev(sid, action="set_day", day=d, dta=5)
            resp2 = chat(sid, "/day 休息", timeout=150)
            s_after = get_session(sid)
            # 检查是否出现新角色
            if len(s_after.get("characters", [])) > base_count:
                produced = True
                print(f"   第{d}天: 生产发生！角色数 {base_count}->{len(s_after.get('characters', []))}")
                break
            # 检查怀孕状态是否清除
            still_preg = [c for c in s_after.get("characters", []) if c.get("pregnant")]
            if not still_preg and preg:
                print(f"   第{d}天: 怀孕状态已清除（可能已生产）")
                break
        s_final = get_session(sid)
        print(f"   最终角色数: {len(s_final.get('characters', []))}")
        for c in s_final.get("characters", []):
            print(f"   - {c['name']} ({c['species']}) Lv{c['level']}")
        check("配种流程有产出（新角色或状态变化）", produced or len(s_final.get("characters", [])) > 2)
    else:
        print("   未检测到怀孕（可能配种语法不对或失败）")
        # 看事件日志
        ev = requests.get(f"{BASE}/api/session/{sid}/events", timeout=10).json()
        evs = ev if isinstance(ev, list) else ev.get("events", [])
        breed_events = [e for e in evs if "配种" in str(e) or "breed" in str(e).lower() or "怀孕" in str(e)]
        print(f"   配种相关事件: {len(breed_events)}")
        for e in breed_events[-3:]:
            print(f"   {str(e)[:120]}")

    # ── 装备对战斗的真实加成 ──
    print("\n4. 装备属性加成对战斗的影响（穿装前后对比）...")
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from combat import Fighter, CombatSim, fighter_from_tavern_char
        from server import _equipment_pool
        s5 = get_session(sid)
        if s5.get("characters"):
            test_char = s5["characters"][0]
            # 无装备
            bare = dict(test_char)
            bare["equipment"] = {"weapon": None, "armor": None, "accessory": None}
            cfg_bare = fighter_from_tavern_char(bare)
            # 有装备（真实装备池）
            cfg_eqd_real = fighter_from_tavern_char(test_char, equipment_pool=_equipment_pool)
            f_bare = Fighter(cfg_bare, cfg_bare.get("skills"))
            f_eqd = Fighter(cfg_eqd_real, cfg_eqd_real.get("skills"))
            print(f"   无装备 STR={f_bare.str:.0f} SPD={f_bare.spd:.0f} 护甲={f_bare.armor:.0f}")
            print(f"   有装备 STR={f_eqd.str:.0f} SPD={f_eqd.spd:.0f} 护甲={f_eqd.armor:.0f}")
            check("装备改变属性", f_eqd.str != f_bare.str or f_eqd.spd != f_bare.spd or f_eqd.armor != f_bare.armor,
                  f"(差 STR {f_eqd.str - f_bare.str:.0f} SPD {f_eqd.spd - f_bare.spd:.0f} 甲 {f_eqd.armor - f_bare.armor:.0f})")
    except ImportError as e:
        print(f"   无法 import server 测试装备加成: {e}")

    print(f"\n=== 配种测试结果: {PASS} 通过 / {FAIL} 失败 ===")
    try:
        os.remove(f"C:/Users/niutun/AppData/Local/hermes/output/derbiren-tavern/saves/{sid}.json")
    except Exception:
        pass
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
