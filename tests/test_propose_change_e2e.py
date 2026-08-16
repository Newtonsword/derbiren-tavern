# -*- coding: utf-8 -*-
"""
P0-2 世界权限模型端到端测试：AI 输出 [PROPOSE_CHANGE] 标签 → 引擎裁决
直接测 _engine_adjudicate 的完整流程（从 server.py 加载真实函数）
"""
import requests, json, sys, os, re

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

def main():
    print("=== P0-2 世界权限模型端到端测试 ===")

    # 直接加载 server 的裁决函数（不启动服务，纯逻辑验证）
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from server import _engine_adjudicate, _inject_propose_notes, PROPOSE_CHANGE_RE

    # 1. 允许的提议（招募）→ 批准
    reply1 = "一只魔物来了 [PROPOSE_CHANGE: 招募一只新魔物 猫龙] 它很可爱"
    clean1, notes1 = _engine_adjudicate(reply1)
    print("\n1. 允许提议（招募）:")
    print(f"   清理后: {clean1.strip()[:60]}")
    print(f"   裁决: {notes1}")
    check("招募提议被批准", any("批准" in n for n in notes1))
    check("标签从回复移除", "[PROPOSE_CHANGE" not in clean1)

    # 2. 禁区提议（改 HP）→ 拒绝
    reply2 = "我觉得应该 [PROPOSE_CHANGE: 把玩家HP改成满] 这样更好"
    clean2, notes2 = _engine_adjudicate(reply2)
    print("\n2. 禁区提议（改HP）:")
    print(f"   裁决: {notes2}")
    check("改HP被拒绝", any("拒绝" in n for n in notes2))

    # 3. 未知提议 → 拒绝
    reply3 = "我想 [PROPOSE_CHANGE: 把天气变成下雨天]"
    clean3, notes3 = _engine_adjudicate(reply3)
    print("\n3. 未知提议（改天气）:")
    print(f"   裁决: {notes3}")
    check("未知变更被拒绝", any("拒绝" in n for n in notes3))

    # 4. 混合：允许+禁止并存
    reply4 = "[PROPOSE_CHANGE: 招募一只史莱姆] 还有 [PROPOSE_CHANGE: 给主角加100金币]"
    clean4, notes4 = _engine_adjudicate(reply4)
    print("\n4. 混合提议:")
    for n in notes4:
        print(f"   {n}")
    check("混合提议正确处理", len(notes4) == 2)
    check("招募被批准", any("批准" in n for n in notes4))
    check("金币被拒绝", any("拒绝" in n for n in notes4))

    # 5. 无提议原样返回
    reply5 = "正常叙述文本没有标签"
    clean5, notes5 = _engine_adjudicate(reply5)
    check("无提议无裁决", notes5 == [] and clean5 == reply5)

    # 6. _inject_propose_notes 注入格式（AI 可见、玩家不可见）
    injected = _inject_propose_notes("叙述内容", ["✅ 系统已批准：招募一只史莱姆"])
    print("\n6. 注入格式:")
    print(f"   {injected}")
    check("注入包含引擎裁决标记", "[引擎裁决]" in injected)
    check("注入保留原文", injected.startswith("叙述内容"))

    # 7. 真实 API：AI 对话中如果输出 propose 标签会被引擎拦截
    print("\n7. API 端到端：触发 AI 提议...")
    r = requests.post(f"{BASE}/api/session/new", json={
        "player_name": "权限测试", "char_name": "吱吱", "char_species": "猫龙"}, timeout=60)
    sid = r.json()["session_id"]
    # 直接给 AI 一个引导它提议的消息（看它是否会输出 propose 标签被拦截）
    resp = requests.post(f"{BASE}/api/session/{sid}/chat", json={
        "message": "我想让地下城发生点变化——你觉得该不该增加一只新魔物来帮忙？"}, timeout=120)
    narr = resp.json().get("narrative", "")
    print(f"   AI 回复[:120]: {narr[:120]}")
    # 检查回复中是否有被清理的 propose 痕迹
    check("API 对话正常返回", len(narr) > 0)

    print(f"\n=== P0-2 测试结果: {PASS} 通过 / {FAIL} 失败 ===")
    try:
        os.remove(f"C:/Users/niutun/AppData/Local/hermes/output/derbiren-tavern/saves/{sid}.json")
    except Exception:
        pass
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
