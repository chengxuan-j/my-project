"""实时通道测试：老人端在线时，家属发传话 → SSE 应立刻收到 dog_relay 事件。"""
import json
import time

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
ts = str(int(time.time()))[-6:]
FAM = f"famrt{ts}"
ELD = f"eldrts{ts}"
PW = "Test123456"


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


def read_events(url, stop_after, out, ready_event):
    """订阅 SSE，最多读 stop_after 秒。"""
    try:
        with httpx.stream("GET", url, timeout=None) as resp:
            ready_event.set()
            deadline = time.time() + stop_after
            for line in resp.iter_lines():
                if time.time() > deadline:
                    break
                if line and line.startswith("event:"):
                    etype = line.split("event:", 1)[1].strip()
                elif line and line.startswith("data:"):
                    try:
                        data = json.loads(line.split("data:", 1)[1].strip())
                    except Exception:
                        continue
                    data["_event"] = etype
                    out.append(data)
                    if etype == "dog_relay":
                        break
    except Exception as e:
        out.append({"_error": str(e)})


def main():
    rf = httpx.post(
        f"{BASE}/auth/register",
        json={"username": FAM, "password": PW, "role": "family", "name": "实时家属"},
        timeout=30,
    )
    if rf.status_code != 200:
        print("注册家属失败:", rf.text[:200])
        return
    fam_tok = rf.json()["access_token"]

    re_ = httpx.post(
        f"{BASE}/auth/register",
        json={"username": ELD, "password": PW, "role": "elderly", "name": "实时老人"},
        timeout=30,
    )
    if re_.status_code != 200:
        print("注册老人失败:", re_.text[:200])
        return
    eld = re_.json()
    eld_tok = eld["access_token"]
    elderly_id = eld["user_id"]

    rb = httpx.post(
        f"{BASE}/family/bind",
        json={
            "elderly_username": ELD,
            "invite_code": eld.get("invite_code"),
            "relationship_name": "儿子",
        },
        headers=h(fam_tok),
        timeout=30,
    )
    if rb.status_code != 200:
        print("绑定失败:", rb.text[:200])
        return
    print(f"[1] 准备完成 elderly_id={elderly_id}")

    import threading

    events = []
    ready = threading.Event()
    url = f"{BASE}/events/stream?token={eld_tok}"
    t = threading.Thread(target=read_events, args=(url, 12, events, ready), daemon=True)
    t.start()
    ready.wait(5)
    time.sleep(1)
    print("[2] 老人端已连上 SSE，家属现在发传话...")

    rr = httpx.post(
        f"{BASE}/dog/relay",
        json={
            "elderly_user_id": elderly_id,
            "relation": "儿子",
            "content": "今天降温，多穿点衣裳",
        },
        headers=h(fam_tok),
        timeout=30,
    )
    print(f"[3] 家属发传话 -> {rr.status_code} {rr.text[:200]}")

    t.join(timeout=15)
    got = [e for e in events if e.get("_event") == "dog_relay"]
    if got:
        e = got[0]
        print(f"[4] ✅ 老人端实时收到 dog_relay：{e.get('text')} (message_id={e.get('message_id')})")
    else:
        print(f"[4] ❌ 老人端未收到 dog_relay，收到的原始帧：{events}")


if __name__ == "__main__":
    main()
