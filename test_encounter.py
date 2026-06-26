#!/usr/bin/env python
"""derbiren-tavern 验证测试 — 重点测 ENCOUNTER 注入 + 审查AI + 角色面板"""
import json, time, urllib.request, sys

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

# 新建会话
r = api("/api/session/new")
sid = r["session_id"]
chars = r.get("characters", [])
print(f"✅ 会话: {sid} | 初始角色: {len(chars)}个")

if not chars:
    print("❌ 初始角色为0！")
    sys.exit(1)

for c in chars:
    print(f"   - {c['name']} Lv.{c['level']} 技能:{len(c.get('skills',[]))}个")

# ═══ ENCOUNTER 测试: 连续10轮探索 ═══
print("\n═══ ENCOUNTER 注入测试 (10轮) ═══")
encounter_hits = 0
for i in range(10):
    r = api("/api/chat", {"session_id": sid, "message": f"/day 1 探索"})
    n = r.get("narrative", "")
    if not n:
        print(f"  第{i+1}轮: ❌ 空响应")
        continue
    has_enc = '[ENCOUNTER]' in n
    has_dmg = '[DMG:' in n or '[DMG：' in n
    has_review = '⚠️ [系统]' in n
    if has_enc:
        encounter_hits += 1
    print(f"  第{i+1}轮: {len(n)}字 | ENC={'✅' if has_enc else '❌'} | DMG={'✅' if has_dmg else '❌'} | 审查={'✅' if has_review else '❌'}")
    time.sleep(0.3)

print(f"\n  📊 ENCOUNTER触发: {encounter_hits}/10 ({encounter_hits*10}%)")

# ═══ 检查面板（从 session/new 直接拿） ═══
r = api("/api/session/new")
sid2 = r["session_id"]
chars2 = r.get("characters", [])
print(f"\n═══ 新会话面板: {len(chars2)}个角色 ═══")
for c in chars2:
    print(f"   - {c['name']} Lv.{c['level']} ({c['species']}) 技能:{len(c.get('skills',[]))}")

# ═══ 审查AI测试: 触发战斗场景 ═══
print("\n═══ 审查AI战斗检测 ═══")
sid3 = api("/api/session/new")["session_id"]
for i in range(3):
    r = api("/api/chat", {"session_id": sid3, "message": f"/day 1 锻炼"})
    n = r.get("narrative", "")
    fight_words = ['挥爪','咬','攻','打','踢','刺','斩','扑','撞','射','撕','魔法','吐息']
    has_fight = any(w in n for w in fight_words)
    has_dmg = '[DMG:' in n or '[DMG：' in n
    has_review = '⚠️ [系统]' in n
    print(f"  第{i+1}轮: {len(n)}字 | 战斗词:{has_fight} | DMG:{has_dmg} | 审查警告:{has_review}")
    if has_fight and not has_dmg and has_review:
        print(f"     ✅ 审查AI正确标记了缺少DMG标签!")
    time.sleep(0.3)

print("\n✅ 测试完成")
