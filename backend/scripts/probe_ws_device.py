# -*- coding: utf-8 -*-
"""模拟 ESP32 设备连小智 WS，验证发声链路（2026-10-16）。

链路：本脚本以"设备"身份连 ws://127.0.0.1:8001/xiaozhi/v1/ 并发 hello 登记
→ 确认 /devices 出现该设备 → push_to_dog 下发一句话 → 统计收到的 TTS 音频帧。
收到音频帧 = 发声链路全通（不等真狗，软件先行自测）。
"""
import asyncio
import json
import sys

sys.path.insert(0, "E:/elderly_companion/backend")
import os  # noqa: E402

os.chdir("E:/elderly_companion/backend")

import aiohttp  # noqa: E402

DEVICE_ID = "test_dog_001"
WS_URL = "ws://127.0.0.1:8001/xiaozhi/v1/"
LISTEN_SECONDS = 20


async def main():
    frames = 0
    text_msgs = []
    welcome = None

    async def device_loop():
        nonlocal frames, welcome
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(WS_URL) as ws:
                await ws.send_json({
                    "type": "hello",
                    "device_id": DEVICE_ID,
                    "audio_params": {
                        "format": "opus", "sample_rate": 16000,
                        "channels": 1, "frame_duration": 60,
                    },
                })
                print("已发 hello，等待 welcome …")
                try:
                    async for msg in ws:
                        if msg.type is aiohttp.WSMsgType.BINARY:
                            frames += 1
                        elif msg.type is aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data or "{}")
                            if welcome is None and data.get("type") in (None, "hello"):
                                welcome = data
                                print("welcome 类型:", data.get("type"), "| 键:", sorted(data.keys())[:6])
                            else:
                                text_msgs.append(str(data)[:80])
                except Exception as e:  # noqa: BLE001
                    print("WS 循环结束:", e)

    task = asyncio.create_task(device_loop())
    await asyncio.sleep(3)

    # 1. 设备是否登记
    async with aiohttp.ClientSession() as s:
        async with s.get("http://127.0.0.1:8003/devices") as r:
            devices = (await r.json()).get("online_devices", [])
    print(f"/devices = {devices}")

    # 2. 下发一句话（关怀话术链路同款入口）
    from app.services import care_speech  # noqa: E402
    from app.services.dog_control import push_to_dog  # noqa: E402

    speech, src = await care_speech.pick_speech("happy", DEVICE_ID, "开心")
    print(f"话术[{src}]: {speech}")
    spoke = await push_to_dog(speech)
    print(f"push_to_dog -> {spoke}")

    # 3. 听 TTS 音频帧
    await asyncio.sleep(LISTEN_SECONDS)
    task.cancel()
    print(f"\n结果：收到音频帧 {frames} 个，文本消息 {len(text_msgs)} 条")
    if frames > 0:
        print("✅ 发声链路全通：TTS 音频已送达设备端")
    else:
        print("❌ 未收到音频帧，链路有断点（看小智服务日志）")
    for t in text_msgs[:5]:
        print("  文本:", t)


asyncio.run(main())
