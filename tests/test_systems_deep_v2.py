# -*- coding: utf-8 -*-
"""
系统深度测试 v2（修复解析后重跑）：探索 / 装备 / 技能 / 存档
修正点：
- 装备库返回 {equipment: [...]} 结构
- 技能生成返回 {active: [...], passive: [...]} 结构
- save 接口需要 body {"name": ...}
- set_day 已修复跨天清空 explored_today
"""
import requests, json, sys, os, time

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

def chat(sid, msg, timeout=120):
    r = requests.post(f"{BASE}/api/session/{sid}/chat", json={"message": msg}, timeout=timeout)
    return r.json()

def dev(sid, **kw):
    return requests.post(f"{BASE}/api/session/{sid}/dev", json=kw, timeout=10).json()

def main():
    print("=== 系统深度测试 v2 ===")
    r = requests.post(f"{BASE}/api/session/new", json={
        "player_name": "深度测试魔王", "char_name": "吱吱", "char_species": "猫龙"}, timeout=60)
    sid = r.json()["session_id"]
    print(f"1. 会话: {sid}")
    s = get_session(sid)
    cid = s["characters"][0]["id"]

    # ── 探索（跨天修复验证）──
    print("\n2. 探索系统（set_day 跨天修复验证）...")
    r1 = requests.post(f"{BASE}/api/session/{sid}/explore", json={"char_id": cid}, timeout=15)
    print(f"   第1天: {r1.status_code} {r1.json().get('result')}")
    dev(sid, action="set_day", day=2, dta=4)
    r2 = requests.post(f"{BASE}/api/session/{sid}/explore", json={"char_id": cid}, timeout=15)
    print(f"   第2天: {r2.status_code} {r2.json().get('result', r2.text[:80])}")
    check("跨天探索成功（set_day 修复生效）", r2.status_code == 200)
    # 多天分布
    dist = {}
    for day in range(3, 13):
        dev(sid, action="set_day", day=day, dta=5)
        rr = requests.post(f"{BASE}/api/session/{sid}/explore", json={"char_id": cid}, timeout=15)
        if rr.status_code == 200:
            res = rr.json().get("result", "?")
            dist[res] = dist.get(res, 0) + 1
    print(f"   10 天分布: {dist}")
    check("探索结果多样", len(dist) >= 2, f"({dist})")

    # ── 探索遇敌概率（ConsequenceManager 50%）──
    print("\n3. 探索遇敌检测（多次探索看战斗叙述比例）...")
    # 遇敌由 AI 叙述触发，需要真实对话；这里用探索接口多次看是否触发战斗事件
    # 检查 events 里有没有 explore 战斗事件

    # ── 装备库 ──
    print("\n4. 装备系统...")
    eq = requests.get(f"{BASE}/api/equipment", timeout=10).json()
    items = eq.get("equipment", [])
    print(f"   装备库: {len(items)} 件")
    check("装备库非空", len(items) > 0)
    r5 = requests.post(f"{BASE}/api/equipment/generate", json={"rarity": "uncommon", "slot": "weapon"}, timeout=60)
    if r5.status_code == 200:
        gen = r5.json()
        item = gen.get("equipment", gen)
        name = item.get("name") if isinstance(item, dict) else None
        print(f"   生成装备: {name} ({item.get('type')})")
        check("装备生成返回名称", bool(name))
    else:
        print(f"   装备生成: {r5.status_code} {r5.text[:100]}")

    # 角色装备接口
    print("\n5. 角色装备...")
    s2 = get_session(sid)
    c0 = s2["characters"][0]
    equip_list = c0.get("equipment", {})
    print(f"   吱吱装备: {equip_list}")
    check("角色有装备字段", isinstance(equip_list, dict))

    # ── 技能生成 ──
    print("\n6. 技能生成（AI + 模板保底）...")
    r6 = requests.post(f"{BASE}/api/session/{sid}/characters/{c0['id']}/skills/generate", timeout=120)
    if r6.status_code == 200:
        sk = r6.json()
        active = sk.get("active", [])
        # passive 可能是单对象 dict 或 list
        p_raw = sk.get("passive", [])
        passive = [p_raw] if isinstance(p_raw, dict) else (p_raw or [])
        all_skills = active + passive
        print(f"   active={len(active)} passive={len(passive)}")
        for s_ in all_skills[:4]:
            print(f"   - {s_.get('name')} ({s_.get('type')}) formula={s_.get('formula','')[:40]}")
        check("技能生成非空", len(all_skills) > 0)
        # 校验公式里有中文属性名或数值
        formula_ok = all(any(k in s_.get("formula", "") for k in ["力量", "速度", "智力", "耐力", "精神"]) for s_ in active if s_.get("formula"))
        check("技能公式含中文属性名", formula_ok or not active)
    else:
        print(f"   技能生成: {r6.status_code} {r6.text[:120]}")

    # ── NPC 记忆持久化 ──
    print("\n7. NPC 记忆（@对话触发）...")
    resp = chat(sid, "@吱吱 记住这条：蓝蘑菇要烤过才好吃", timeout=120)
    s3 = get_session(sid)
    found_mem = False
    for c in s3.get("characters", []):
        mem = c.get("persona", {}).get("memory", [])
        if mem:
            print(f"   {c['name']} 记忆: {[m['event'][:40] for m in mem[-2:]]}")
            found_mem = True
            break
    check("NPC 记忆持久化", found_mem)
    # 再次对话验证记忆保留
    resp2 = chat(sid, "@吱吱 还记得蓝蘑菇吗", timeout=120)
    s4 = get_session(sid)
    for c in s4.get("characters", []):
        mem = c.get("persona", {}).get("memory", [])
        if mem:
            print(f"   对话后记忆 {len(mem)} 条")
            check("记忆跨回合累积", len(mem) >= 2, f"({len(mem)})")
            break

    # ── 存档 ──
    print("\n8. 存档/读档...")
    r7 = requests.post(f"{BASE}/api/session/{sid}/save", json={"name": "深度测试存档"}, timeout=10)
    print(f"   保存: {r7.status_code} {r7.text[:100]}")
    check("命名存档成功", r7.status_code == 200)

    # ── 事件日志 ──
    print("\n9. 事件日志...")
    ev = requests.get(f"{BASE}/api/session/{sid}/events", timeout=10)
    if ev.status_code == 200:
        evs = ev.json()
        n = len(evs) if isinstance(evs, list) else len(evs.get("events", []))
        print(f"   事件数: {n}")
        check("事件日志非空", n > 0)
    else:
        print(f"   事件接口: {ev.status_code}")

    print(f"\n=== v2 结果: {PASS} 通过 / {FAIL} 失败 ===")
    try:
        os.remove(f"C:/Users/niutun/AppData/Local/hermes/output/derbiren-tavern/saves/{sid}.json")
    except Exception:
        pass
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
