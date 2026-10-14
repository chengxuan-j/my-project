"""端到端测试：家属端「让小狗传话」完整链路。

重点验证：老人发作时不在线 → 之后上线补播（GET /dog/relays）能否拿到。
"""
import time

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
ts = str(int(time.time()))[-6:]
FAM = f"famtest{ts}"
ELD = f"eldtest{ts}"
PW = "Test123456"


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


def main():
    # 1) 注册家属 + 老人
    rf = httpx.post(
        f"{BASE}/auth/register",
        json={"username": FAM, "password": PW, "role": "family", "name": "测试家属"},
        timeout=30,
    )
    print(f"[1] 注册家属 -> {rf.status_code}")
    if rf.status_code != 200:
        print("   失败:", rf.text[:300])
        return
    fam_tok = rf.json()["access_token"]

    re_ = httpx.post(
        f"{BASE}/auth/register",
        json={"username": ELD, "password": PW, "role": "elderly", "name": "测试老人"},
        timeout=30,
    )
    print(f"[2] 注册老人 -> {re_.status_code}")
    if re_.status_code != 200:
        print("   失败:", re_.text[:300])
        return
    eld = re_.json()
    eld_tok = eld["access_token"]
    elderly_id = eld.get("user_id")
    invite = eld.get("invite_code")
    print(f"   elderly_id={elderly_id} invite_code={invite}")

    # 2) 家属绑定老人
    rb = httpx.post(
        f"{BASE}/family/bind",
        json={
            "elderly_username": ELD,
            "invite_code": invite,
            "relationship_name": "女儿",
        },
        headers=h(fam_tok),
        timeout=30,
    )
    print(f"[3] 家属绑定老人 -> {rb.status_code} {rb.text[:200]}")
    if rb.status_code != 200:
        return

    # 3) 关键场景：老人端此时「不在线」（没连 SSE），家属发传话
    rr = httpx.post(
        f"{BASE}/dog/relay",
        json={
            "elderly_user_id": elderly_id,
            "relation": "女儿",
            "content": "记得按时吃药",
        },
        headers=h(fam_tok),
        timeout=30,
    )
    print(f"[4] 家属发传话（老人离线）-> {rr.status_code}")
    print(f"    {rr.text[:300]}")
    if rr.status_code != 200:
        return

    # 4) 老人上线：拉取待补播的传话
    rp = httpx.get(f"{BASE}/dog/relays", headers=h(eld_tok), timeout=30)
    print(f"[5] 老人上线补播 GET /dog/relays -> {rp.status_code}")
    print(f"    {rp.text[:400]}")
    if rp.status_code == 200:
        relays = rp.json().get("relays", [])
        if relays:
            print(f"    ✅ 补播到 {len(relays)} 条，最新一句：{relays[-1]['text']}")
        else:
            print("    ❌ 没补播到任何内容")

        # 5) 再拉一次应为空（不重复播报）
        rp2 = httpx.get(f"{BASE}/dog/relays", headers=h(eld_tok), timeout=30)
        n2 = len(rp2.json().get("relays", []))
        print(f"[6] 二次拉取 -> 剩余 {n2} 条 " + ("✅ 不重复" if n2 == 0 else "❌ 会重复播报"))

    # 6) 越权校验：老人不能给自己发传话
    rv = httpx.post(
        f"{BASE}/dog/relay",
        json={
            "elderly_user_id": elderly_id,
            "relation": "女儿",
            "content": "测试越权",
        },
        headers=h(eld_tok),
        timeout=30,
    )
    print(f"[7] 越权校验(老人账号调 /dog/relay) -> {rv.status_code} " + ("✅ 已拦截" if rv.status_code >= 400 else "❌ 未拦截"))


if __name__ == "__main__":
    main()
