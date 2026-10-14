"""后台监控：等待物理狗唤醒并建链，连上后自动触发一次发声测试。

用法：
  python monitor_dog.py [超时秒数，默认180]
狗连上 8001 后，会自动 GET /devices 取 device_id，并 POST /say 一句测试语，
验证「连上 -> 登记 -> TTS -> 狗喇叭出声」整条链路。结果打印到 stdout。
"""
import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

HTTP_BASE = "http://127.0.0.1:8003"
TEST_TEXT = "测试，我是机器狗，已成功连接到服务器"


def get_devices():
    try:
        with urllib.request.urlopen(f"{HTTP_BASE}/devices", timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"online_devices": [], "error": str(e)}


def say(device_id, text):
    url = f"{HTTP_BASE}/devices/{urllib.parse.quote(device_id)}/say"
    req = urllib.request.Request(
        url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return -1, str(e)


def main():
    timeout = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    rounds = max(1, timeout // 3)
    print(f"[MONITOR] 开始监控，最长等待 {timeout}s，每 3s 轮询 /devices ...", flush=True)
    for i in range(rounds):
        devs = get_devices()
        ds = [d for d in devs.get("online_devices", []) if d != "test_dog_001"]
        if ds:
            print(f"[MONITOR] 第{i+1}次：检测到狗上线 device_id={ds}", flush=True)
            did = ds[0]
            # TTS 后台初始化需要几秒，先等 8s 再 say
            print("[MONITOR] 等待 8s 让后台 TTS 初始化完成 ...", flush=True)
            time.sleep(8)
            status, body = say(did, TEST_TEXT)
            print(f"[MONITOR] POST /say -> HTTP {status} | {body}", flush=True)
            if status == 200:
                print("[MONITOR] ✅ 发声测试成功：狗应该已经出声了", flush=True)
            else:
                print("[MONITOR] ⚠️ /say 未返回 200，请检查 TTS 是否就绪或 device_id 是否正确", flush=True)
            return
        if i % 5 == 0:
            print(f"[MONITOR] 第{i+1}次：尚无狗连接（/devices={devs}）", flush=True)
        time.sleep(3)
    print("[MONITOR] 超时：监控周期内未检测到狗连上 8001，请先唤醒狗（说唤醒词）", flush=True)


if __name__ == "__main__":
    main()
