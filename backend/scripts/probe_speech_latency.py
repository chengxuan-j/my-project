# -*- coding: utf-8 -*-
"""语音链路耗时实测：TTS 合成 + ASR 识别（2026-10-16）。

做法：先用 TTS 把一句话合成成音频（拿到真实人声内容），
再把这段音频喂给 ASR，量出「上传+提交+轮询」的端到端耗时。
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, "E:/elderly_companion/backend")
os.chdir("E:/elderly_companion/backend")

import httpx  # noqa: E402

from app.speech.speech_client import _client as sc  # noqa: E402

TEXT = "今天天气挺好的，我出去走了走，顺便买了点菜"


async def main():
    print("=== 1) TTS 合成耗时 ===")
    t = time.perf_counter()
    url = await sc.synthesize(TEXT)
    t_tts = time.perf_counter() - t
    print("  耗时 %.2fs" % t_tts)
    print("  音频 URL:", (url or "")[:70])

    print("=== 2) 下载音频 ===")
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(url)
        audio = r.content
    print("  大小 %.1f KB" % (len(audio) / 1024))

    print("=== 3) ASR 全链路（上传 OSS + 提交 + 轮询）耗时 ===")
    t = time.perf_counter()
    text = await sc.transcribe(audio, filename="probe.wav")
    t_asr = time.perf_counter() - t
    print("  耗时 %.2fs" % t_asr)
    print("  识别结果:", (text or "<空>")[:80])

    print()
    print("=== 汇总 ===")
    print("  TTS %6.2fs" % t_tts)
    print("  ASR %6.2fs" % t_asr)


asyncio.run(main())
