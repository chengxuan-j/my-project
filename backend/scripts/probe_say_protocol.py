# -*- coding: utf-8 -*-
"""协议级验证：say 路径下发设备时到底发了哪些 JSON 消息（2026-10-16）。

背景：真狗收到音频帧却不播放，怀疑缺少 {"type":"tts","state":"start"}
（正常对话路径由 send_stt_message 发送，say 路径绕过了 STT）。
本脚本以"设备"身份连上，直接调用 /devices/<自己>/say，抓全部 JSON 消息。
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, "E:/elderly_companion/backend")
os.chdir("E:/elderly_companion/backend")

import aiohttp  # noqa: E402

DEVICE_ID = "probe_proto_001"
WS_URL = "ws://127.0.0.1:8001/xiaozhi/v1/"
HTTP_BASE = "http://127.0.0.1:8003"

received = []      # (kind, payload)
frames = 0


async def device_loop():
    global frames
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
            try:
                async for msg in ws:
                    if msg.type is aiohttp.WSMsgType.BINARY:
                        frames += 1
                    elif msg.type is aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data or "{}")
                        received.append((data.get("type"), data))
            except Exception as e:  # noqa: BLE001
                print("WS 循环结束:", e)


async def main():
    task = asyncio.create_task(device_loop())
    await asyncio.sleep(3)

    async with aiohttp.ClientSession() as s:
        async with s.get(f"{HTTP_BASE}/devices") as r:
            print("设备列表:", (await r.json()).get("online_devices"))

    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{HTTP_BASE}/devices/{DEVICE_ID}/say",
            json={"text": "协议验证：测试一段话。"},
        ) as r:
            print("say 接口返回:", r.status, await r.text())

    await asyncio.sleep(8)
    task.cancel()

    print("\n===== 服务端发给设备的 JSON 消息序列 =====")
    for i, (t, d) in enumerate(received, 1):
        print(f"  {i}. type={t} | {json.dumps(d, ensure_ascii=False)[:110]}")
    print(f"\n音频帧数 = {frames}")

    has_tts_start = any(
        t == "tts" and d.get("state") == "start" for t, d in received
    )
    print("包含 tts start :", "✅ 是" if has_tts_start else "❌ 否")


asyncio.run(main())
