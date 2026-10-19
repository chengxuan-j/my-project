# -*- coding: utf-8 -*-
"""预合成"接话"短句音频（2026-10-19）。

用途：老人话音一落时前端立即播放（<200ms），后台照常跑完整回复链路，
让体感从"等 4 秒"变成"秒回"，完整回复随后接上。

TTS 返回的是 DashScope 临时 URL（会过期），所以这里**下载 mp3 落盘**到
frontend/public/audio/ack/，变成永久静态资源，前端直接 <audio> 预加载。
"""
import os
import sys

import httpx

sys.path.insert(0, "E:/elderly_companion/backend")
os.chdir("E:/elderly_companion/backend")

from app.speech.speech_client import SpeechClient  # noqa: E402

# 4 句接话：短、自然、可轮换（避免每句都一样显得机械）
LINES = [
    ("ack_1", "嗯，我在呢。"),
    ("ack_2", "哎，您说。"),
    ("ack_3", "好，我听着呢。"),
    ("ack_4", "您稍等等，我想想。"),
]

OUT_DIR = "E:/elderly_companion/frontend/public/audio/ack"


async def main():
    client = SpeechClient()
    if not client.is_configured:
        print("未配置 QWEN_API_KEY，无法合成")
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, text in LINES:
        url = await client.synthesize(text)
        r = await client._client().get(url)
        if r.status_code != 200:
            print(f"  {name}: 下载失败 HTTP {r.status_code}")
            continue
        path = os.path.join(OUT_DIR, f"{name}.mp3")
        with open(path, "wb") as f:
            f.write(r.content)
        print(f"  {name}.mp3  {len(r.content):>6} bytes  <- {text}")


import asyncio  # noqa: E402

asyncio.run(main())
