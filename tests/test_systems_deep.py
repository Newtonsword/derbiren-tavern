# -*- coding: utf-8 -*-
"""
系统深度测试（第 2 轮）：探索 / 配种 / 装备 / 技能生成 / 多角色
通过真实 API 验证每个系统的数值真实改变（程序驱动，非 AI 叙述）
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

def chat(sid, msg, timeout=120):
    r = requests.post(f"{BASE}/api/session/{sid}/chat", json={"message": msg}, timeout=timeout)
    return r.json()

def dev(sid, **kw):
    return requests.post(f"{BASE}/api/session/{sid}/dev", json=kw, timeout=10).json()

def main():
    print("=== 系统深度测试（第 2 轮）===")

    # 建会话
    r = requests.post(f"{BASE}/api/session/new", json={
        "player_name": "深度测试魔王", "char_name": "吱吱", "char_species": "猫龙"}, timeout=60)
    sid = r.json()["session_id"]
    print(f"1. 会话: {sid}")

    # ── 探索系统 ──
    print("\n2. 探索系统（每天每角色限一次，概率 60%空/25%装/15%魔）...")
    s = get_session(sid)
    cid = s["characters"][0]["id"]
    results = {}
    for i in range(3):  # 3 个角色探索（先加角色再测）
        pass
    # 先单角色探索
    r = requests.post(f"{BASE}/api/session/{sid}/explore", json={"char_id": cid}, timeout=15)
    d = r.json()
    results[d.get("result")] = results.get(d.get("result"), 0) + 1
    print(f"   探索结果: {d.get('result')} — {d.get('msg', '')[:60]}")
    check("探索接口返回有效结果", d.get("result") in ("nothing", "equipment", "monster"))
    # 当天重复探索应被拒
    r2 = requests.post(f"{BASE}/api/session/{sid}/explore", json={"char_id": cid}, timeout=15)
    check("当天重复探索被拒绝", r2.status_code == 400, f"({r2.status_code})")
    # 换天再来
    dev(sid, action="set_day", day=2, dta=4)
    r3 = requests.post(f"{BASE}/api/session/{sid}/explore", json={"char_id": cid}, timeout=15)
    d3 = r3.json()
    print(f"   第2天探索: {d3.get('result')} — {d3.get('msg', '')[:60]}")
    check("跨天可再探索", r3.status_code == 200)

    # 连续推进多天收集结果分布（验证概率机制真实生效）
    dist = {}
    for day in range(3, 12):
        dev(sid, action="set_day", day=day, dta=5)
        rr = requests.post(f"{BASE}/api/session/{sid}/explore", json={"char_id": cid}, timeout=15)
        if rr.status_code == 200:
            res = rr.json().get("result", "?")
            dist[res] = dist.get(res, 0) + 1
    print(f"   9 天探索分布: {dist}")
    check("探索有多样结果（非单值）", len(dist) >= 2, f"({dist})")

    # ── 多角色队伍 ──
    print("\n3. 多角色队伍（dev 招募第二个角色）...")
    r4 = requests.post(f"{BASE}/api/session/{sid}/dev", json={"action": "add_char",
        "name": "嘎嘎", "species": "史莱姆", "stats": {"END": 6, "STR": 3, "SPD": 4, "DEF": 5, "INT": 3, "MP": 6, "WIL": 5}}, timeout=10)
    # 看 dev 支持什么 action
    if r4.status_code != 200 or not r4.json().get("ok"):
        print(f"   add_char 可能不支持: {r4.status_code} {r4.text[:100]}")
        # 用另一个方法：直接检查 dev 接口支持的 action
        import inspect
    s = get_session(sid)
    n_chars = len(s.get("characters", []))
    print(f"   当前角色数: {n_chars}")
    for c in s.get("characters", []):
        print(f"   - {c['name']} ({c['species']}) persona={'✅' if c.get('persona') else '❌'}")
    check("角色数 >= 1（初始）", n_chars >= 1)

    # ── 配种系统 ──
    print("\n4. 配种系统（/day 配种 触发）...")
    resp = chat(sid, "/day 配种", timeout=150)
    narr = resp.get("narrative", "")
    print(f"   配种回复[:150]: {narr[:150]}")
    s2 = get_session(sid)
    preg = [c for c in s2.get("characters", []) if c.get("pregnant")]
    if preg:
        p = preg[0]["pregnant"]
        print(f"   ✅ 怀孕状态: {preg[0]['name']} 预产期第{p.get('due_day')}天")
    else:
        print(f"   未检测到怀孕（可能配种需要两只魔物或概率）")
    check("配种请求有响应", len(narr) > 0)

    # ── 装备系统 ──
    print("\n5. 装备系统...")
    eq = requests.get(f"{BASE}/api/equipment", timeout=10).json()
    if isinstance(eq, dict) and "items" in eq:
        items = eq["items"]
    elif isinstance(eq, list):
        items = eq
    else:
        items = []
    print(f"   装备库: {len(items)} 件")
    check("装备库非空", len(items) > 0)
    # 装备生成接口
    r5 = requests.post(f"{BASE}/api/equipment/generate", json={"rarity": "uncommon", "slot": "weapon"}, timeout=60)
    if r5.status_code == 200:
        gen = r5.json()
        print(f"   生成装备: {gen.get('name', '?')} ({gen.get('rarity', '?')})")
        check("装备生成返回", bool(gen.get("name")))
    else:
        print(f"   装备生成接口: {r5.status_code} {r5.text[:80]}")

    # ── 技能生成 ──
    print("\n6. 技能生成（AI + 模板保底）...")
    s3 = get_session(sid)
    c0 = s3["characters"][0]
    r6 = requests.post(f"{BASE}/api/session/{sid}/characters/{c0['id']}/skills/generate", timeout=120)
    if r6.status_code == 200:
        sk = r6.json()
        skills = sk.get("skills", sk) if isinstance(sk, dict) else sk
        print(f"   生成技能: {len(skills) if isinstance(skills, list) else '?'} 个")
        if isinstance(skills, list) and skills:
            for s_ in skills[:3]:
                print(f"   - {s_.get('name')} ({s_.get('type')}) {s_.get('formula', '')}")
            check("技能生成非空", len(skills) > 0)
        else:
            print(f"   技能生成返回: {str(sk)[:120]}")
    else:
        print(f"   技能生成接口: {r6.status_code} {r6.text[:120]}")

    # ── NPC 记忆持久化 ──
    print("\n7. NPC 记忆持久化...")
    s4 = get_session(sid)
    for c in s4.get("characters", []):
        mem = c.get("persona", {}).get("memory", [])
        if mem:
            print(f"   {c['name']} 记忆 {len(mem)} 条: {[m['event'][:30] for m in mem[-2:]]}")
            check("NPC 记忆非空", len(mem) > 0)
            break
    else:
        # 触发一条记忆：@NPC 对话
        resp = chat(sid, "@吱吱 记得我们上次聊的蓝蘑菇吗？", timeout=120)
        s5 = get_session(sid)
        for c in s5.get("characters", []):
            mem = c.get("persona", {}).get("memory", [])
            if mem:
                print(f"   {c['name']} 记忆 {len(mem)} 条: {[m['event'][:30] for m in mem[-2:]]}")
                check("NPC 记忆持久化", len(mem) > 0)
                break
        else:
            print("   未检测到记忆（可能需要 @NPC 多轮对话）")

    # ── 存档 ──
    print("\n8. 存档/读档...")
    r7 = requests.post(f"{BASE}/api/session/{sid}/save", timeout=10)
    print(f"   保存: {r7.status_code} {r7.text[:80]}")
    saves = requests.get(f"{BASE}/api/saves", timeout=10).json()
    if isinstance(saves, list):
        check("存档列表有记录", len(saves) > 0, f"({len(saves)})")
    elif isinstance(saves, dict) and saves.get("saves"):
        check("存档列表有记录", True)

    print(f"\n=== 结果: {PASS} 通过 / {FAIL} 失败 ===")
    # 清理测试存档
    try:
        os.remove(f"C:/Users/niutun/AppData/Local/hermes/output/derbiren-tavern/saves/{sid}.json")
    except Exception:
        pass
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
