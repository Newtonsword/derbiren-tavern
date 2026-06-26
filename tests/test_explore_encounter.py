"""探索遇敌系统回归测试
验证：探索时AI叙述了遭遇战（通过战斗关键词检测）+ 审查AI标记缺失DMG
"""
import json, urllib.request

BASE = 'http://127.0.0.1:8099'
FIGHT_WORDS = ['战斗','遭遇','伏击','袭来','冲来','窜出','冒出','挡住',
               '袭击','攻击','暗影','蝙蝠','巨鼠','傀儡','毒雾','幽灵',
               '骷髅','藤蔓','怪物','野怪','扑','咬','挥爪']

def api(path, data=None):
    url = BASE + path
    body = json.dumps(data, ensure_ascii=False).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=body,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST' if data else 'GET')
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read())

def test_explore():
    r = api('/api/session/new')
    sid = r['session_id']
    print(f"会话: {sid}")

    enc = 0
    review = 0
    for i in range(10):
        r = api('/api/chat', {'session_id': sid, 'message': f'/day 1 探索'})
        n = r.get('narrative', '')
        has_fight = any(w in n for w in FIGHT_WORDS)
        has_review = '⚠️ [系统]' in n
        if has_fight: enc += 1
        if has_review: review += 1
        status = "⚔️" if has_fight else "🔍"
        print(f"  {status} 探索{i+1}: {len(n)}字 | 审查={'⚠️' if has_review else '✅'}")

    print(f"\n结果: 战斗叙述={enc}/10 | 审查触发={review}/10")
    assert enc >= 5, f"战斗叙述率过低: {enc}/10（预期≥50%）"
    assert review >= 5, f"审查AI触发率过低: {review}/10"
    print("✅ 通过")

if __name__ == '__main__':
    test_explore()
