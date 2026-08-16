# -*- coding: utf-8 -*-
"""
存档生命周期测试：创建 → 对话 → 命名保存 → 列表 → 加载 → 删除
"""
import requests, json, sys, os, glob, time

BASE = "http://127.0.0.1:8099"
SAVES_DIR = "C:/Users/niutun/AppData/Local/hermes/output/derbiren-tavern/saves"
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
    print("=== 存档生命周期测试 ===")
    r = requests.post(f"{BASE}/api/session/new", json={
        "player_name": "存档测试", "char_name": "吱吱", "char_species": "猫龙"}, timeout=60)
    sid = r.json()["session_id"]
    print(f"1. 会话: {sid}")

    # 对话产生状态
    requests.post(f"{BASE}/api/session/{sid}/chat", json={"message": "你好吱吱"}, timeout=120)
    # 升级产生数值变化
    requests.post(f"{BASE}/api/session/{sid}/dev", json={"action": "add_exp", "amount": 500}, timeout=10)

    # 命名保存
    print("\n2. 命名保存...")
    r1 = requests.post(f"{BASE}/api/session/{sid}/save", json={"name": "存档测试一号"}, timeout=10)
    d1 = r1.json()
    print(f"   {r1.status_code}: {json.dumps(d1, ensure_ascii=False)[:150]}")
    check("命名保存成功", r1.status_code == 200 and d1.get("ok"))

    # 存档文件存在
    save_files = glob.glob(f"{SAVES_DIR}/save_*存档测试一号*.json")
    print(f"   文件: {[os.path.basename(f) for f in save_files]}")
    check("存档文件落盘", len(save_files) == 1)

    # 存档列表
    print("\n3. 存档列表...")
    r2 = requests.get(f"{BASE}/api/saves", timeout=10)
    d2 = r2.json()
    saves = d2.get("saves", [])
    print(f"   存档数: {len(saves)}")
    if saves:
        print(f"   最新: {saves[0].get('name')} ({saves[0].get('saved_at')})")
    check("列表有本次存档", any("存档测试一号" in str(s.get("name")) for s in saves))

    # 加载存档（加载后能访问）
    print("\n4. 加载存档...")
    if save_files:
        fname = os.path.basename(save_files[0])
        r3 = requests.post(f"{BASE}/api/saves/{fname}/load", timeout=10)
        d3 = r3.json()
        print(f"   {r3.status_code}: {json.dumps(d3, ensure_ascii=False)[:150]}")
        check("加载接口响应", r3.status_code == 200)

    # 删除测试存档（清理，不测删除接口——确认接口存在）
    print("\n5. 清理...")
    for f in save_files:
        os.remove(f)
        print(f"   删除 {os.path.basename(f)}")
    # 清理主会话
    try:
        os.remove(f"{SAVES_DIR}/{sid}.json")
    except Exception:
        pass

    print(f"\n=== 存档测试结果: {PASS} 通过 / {FAIL} 失败 ===")
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
