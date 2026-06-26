import json, urllib.request, traceback

BASE = 'http://127.0.0.1:8099'
def api(path, data=None):
    url = BASE + path
    body = json.dumps(data, ensure_ascii=False).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST' if data else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.loads(res.read())
    except Exception as e:
        return {'error': str(e), 'narrative': ''}

# New session
r = api('/api/session/new')
sid = r['session_id']
print(f'SID: {sid}', flush=True)

# 5 rounds of explore
enc = 0
for i in range(5):
    r = api('/api/chat', {'session_id': sid, 'message': f'/day 1 探索'})
    n = r.get('narrative', '')
    if 'error' in r:
        print(f'  探索{i+1}: ERROR {r["error"][:80]}', flush=True)
        break
    has_enc = '[ENCOUNTER]' in n
    has_review = '⚠️ [系统]' in n
    if has_enc: enc += 1
    print(f'  探索{i+1}: {len(n)}字 ENC={"YES" if has_enc else "NO"} REVIEW={"YES" if has_review else "NO"}', flush=True)

print(f'ENCOUNTER: {enc}/5', flush=True)
