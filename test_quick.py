#!/usr/bin/env python
"""derbiren-tavern 深度测试：遇敌 + 招募 + 审查AI + 面板"""
import json, time, urllib.request

BASE = "http://127.0.0.1:8099"
HEADERS = {"Content-Type": "application/json; charset=utf-8"}

def api(path, data=None):
    url = BASE + path
    body = json.dumps(data, ensure_ascii=False).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=body, headers=HEADERS, method='POST' if data else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=90) as res:
            return json.loads(res.read())
    except Exception as e:
        return {"error": str(e)}

def chat(sid, msg):
    r = api("/api/chat", {"session_id": sid, "message": msg})
    if r.get("error"):
        print(f"  ❌ API错误: {r['error']}")
    return r

# 新建会话（用新名字避免缓存）
r = api("/api/session/new")
sid = r["session_id"]
print(f"✅ 会话: {sid}")

# ═══ 测试1: 探索遇敌 — 跑5轮 ═══
print("\n═══ 探索遇敌测试 (5轮) ═══")
encounter_hits = 0
for i in range(5):
    r = chat(sid, f"/day 1 探索")
    n = r.get("narrative", "")
    has_enc = '[ENCOUNTER]' in n
    if has_enc:
        encounter_hits += 1
    print(f"  第{i+1}轮: {len(n)}字 | ENCOUNTER={'✅' if has_enc else '❌'} | DMG={'✅' if '[DMG:' in n else '❌'} | 审查提示={'✅' if '⚠️ [系统]' in n else '❌'}")
    time.sleep(0.5)

print(f"\n  📊 ENCOUNTER触发率: {encounter_hits}/5 = {encounter_hits*20}%")

# ═══ 测试2: 面板检查 ═══
print("\n═══ 面板检查 ═══")
r = api(f"/api/session/{sid}/panel")
chars = r.get("characters", [])
print(f"  角色数: {len(chars)}")
for c in chars:
    print(f"    - {c['name']} Lv.{c['level']} ({c['species']}) 技能:{len(c.get('skills',[]))}个")

# ═══ 测试3: 巡逻招募 ═══
print("\n═══ 巡逻招募测试 (5轮) ═══")
recruit_hits = 0
for i in range(5):
    r = chat(sid, f"/day 1 巡逻")
    n = r.get("narrative", "")
    has_recruit = '[NAME_CHOICE]' in n or '起名' in n or '名字' in n
    if has_recruit:
        recruit_hits += 1
        print(f"  第{i+1}轮: {len(n)}字 | 招募✅")
        # 用默认名(1)回应
        r2 = chat(sid, "1")
        n2 = r2.get("narrative", "")
        print(f"    起名回应: {n2[:100]}")
        # 检查面板
        r3 = api(f"/api/session/{sid}/panel")
        chars2 = r3.get("characters", [])
        print(f"    面板角色数: {len(chars2)}")
        for c in chars2[-2:]:
            print(f"      - {c['name']} Lv.{c['level']} 技能:{len(c.get('skills',[]))}个")
        break
    else:
        print(f"  第{i+1}轮: {len(n)}字 | 招募❌")
    time.sleep(0.5)

print(f"\n  📊 招募触发率: {recruit_hits}/5")

# ═══ 测试4: 审查AI — 故意触发战斗 ═══
print("\n═══ 审查AI战斗标签测试 ═══")
# 用"冒险者来袭"触发战斗，看审查AI是否检查DMG
for i in range(3):
    r = chat(sid, f"/day 1 锻炼")
    n = r.get("narrative", "")
    has_fight = any(w in n for w in ['挥爪','咬','攻击','打','踢','刺','斩'])
    has_dmg = '[DMG:' in n or '[DMG：' in n
    has_review = '⚠️ [系统]' in n and '审查' in n
    print(f"  第{i+1}轮: {len(n)}字 | 战斗词:{has_fight} | DMG:{has_dmg} | 审查提示:{has_review}")
    time.sleep(0.5)

print("\n✅ 测试完成")
