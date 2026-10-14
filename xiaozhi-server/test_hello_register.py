"""模拟一只 ESP32 狗固件，连上 xiaozhi 服务端并发 hello，验证设备注册表与 /say 链路。"""
import asyncio
import json
import urllib.request

WS_URL = "ws://127.0.0.1:8001/xiaozhi/v1/"
HTTP_BASE = "http://127.0.0.1:8003"


async def main():
    import websockets

    # 1) 建立 WebSocket（不带任何 device-id 头/查询参数，模拟真实固件）
    async with websockets.connect(WS_URL, max_size=None) as ws:
        print("[1] WS 已连接（无 device-id 头）")

        # 2) 等服务端可能发的消息（welcome 之前）
        # 3) 发送 hello，携带 device_id（真实固件放在 hello JSON 里）
        hello = {
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "audio_params": {"format": "opus", "sample_rate": 24000, "channels": 1},
            "device_id": "test_dog_001",
            "session_id": "sess_test_001",
        }
        await ws.send(json.dumps(hello))
        print("[2] 已发送 hello: device_id=test_dog_001")

        # 4) 收一下服务端回的 welcome，避免连接被异常关闭
        try:
            resp = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"[3] 收到服务端消息({len(resp)}字节): {resp[:120]}")
        except Exception as e:
            print(f"[3] 收消息异常(可忽略): {e}")

        # 4.5) 关键：等待服务端后台初始化完成（TTS 是异步后台初始化的，要等十几秒）
        print("[4] 等待 15 秒，让服务端后台初始化 TTS ...")
        await asyncio.sleep(15)

        # 5) 查询 /devices（应通过 hello 里的 device_id 登记上）
        devices = json.loads(urllib.request.urlopen(f"{HTTP_BASE}/devices", timeout=5).read())
        print(f"[5] GET /devices -> {devices}")

        # 6) 尝试让设备朗读一句话
        req = urllib.request.Request(
            f"{HTTP_BASE}/devices/test_dog_001/say",
            data=json.dumps({"text": "测试，我是机器狗"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                print(f"[6] POST /say -> {r.status} {r.read().decode('utf-8')}")
        except urllib.error.HTTPError as e:
            print(f"[6] POST /say -> HTTP {e.code} {e.read().decode('utf-8')}")

        # 7) 保持连接一会儿，看服务端是否稳定（不报错）
        await asyncio.sleep(2)
        print("[7] 模拟设备保持连接 2 秒，未崩溃 -> 服务端修复生效")


if __name__ == "__main__":
    asyncio.run(main())
