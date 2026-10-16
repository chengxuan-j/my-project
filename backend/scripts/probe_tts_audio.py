# -*- coding: utf-8 -*-
"""验证服务端下发的 TTS 音频是否**有真实声音内容**（2026-10-16）。

背景：真狗能连上、say 返回成功、TTS 日志显示"生成成功"，但狗没声音。
本脚本以独立设备身份（不影响真狗）连小智 WS，让服务端 say 一句话，
把收到的 opus 帧解码成 PCM，计算音量幅度（RMS）：
- 有非静音帧 → 服务端音频数据是好的，问题在真狗固件/状态（音量、播放通路）
- 全是静音/无法解码 → 服务端 TTS 编码链路有问题
"""
import asyncio
import audioop
import json
import sys

sys.path.insert(0, "E:/elderly_companion/backend")
import os  # noqa: E402

os.chdir("E:/elderly_companion/backend")

import aiohttp  # noqa: E402

DEVICE_ID = "probe_dog_audio"
WS_URL = "ws://127.0.0.1:8001/xiaozhi/v1/"
SAMPLE_RATE = 16000


async def main():
    frames = []          # 原始 opus 帧
    pcm_all = bytearray()

    async def device_loop():
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(WS_URL) as ws:
                await ws.send_json({
                    "type": "hello",
                    "device_id": DEVICE_ID,
                    "audio_params": {
                        "format": "opus", "sample_rate": SAMPLE_RATE,
                        "channels": 1, "frame_duration": 60,
                    },
                })
                async for msg in ws:
                    if msg.type is aiohttp.WSMsgType.BINARY:
                        frames.append(msg.data)

    task = asyncio.create_task(device_loop())
    await asyncio.sleep(2.5)

    from app.services.dog_control import push_to_dog  # noqa: E402

    text = "这是一句用来验证音频内容的测试话，一二三四五六七八九十。"
    print("让服务端朗读:", text)
    print("push_to_dog =", await push_to_dog(text))

    await asyncio.sleep(12)
    task.cancel()

    print(f"\n收到 opus 帧: {len(frames)}")
    if not frames:
        print("❌ 没收到音频帧（服务端未下发）")
        return

    # 解码检查音量
    try:
        import opuslib_next as opuslib

        dec = opuslib.Decoder(SAMPLE_RATE, 1)
        ok, rms_list = 0, []
        for f in frames:
            try:
                pcm = dec.decode(f, SAMPLE_RATE * 60 // 1000)
                ok += 1
                pcm_all.extend(pcm)
                rms_list.append(audioop.rms(pcm, 2))
            except Exception:  # noqa: BLE001
                continue
        if rms_list:
            max_rms, avg_rms = max(rms_list), sum(rms_list) / len(rms_list)
            loud = sum(1 for r in rms_list if r > 100)
            print(f"解码成功 {ok}/{len(frames)} 帧")
            print(f"音量 RMS: 最大 {max_rms}, 平均 {avg_rms:.0f}, 超过阈值(>100)的帧 {loud} 个")
            # 存 wav 供人工试听
            import wave

            out = "E:/models/probe_tts_output.wav"
            with wave.open(out, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLE_RATE)
                w.writeframes(bytes(pcm_all))
            print(f"已存 wav: {out}（时长 {len(pcm_all)/2/SAMPLE_RATE:.1f}s）")
            if loud > len(rms_list) * 0.1:
                print("✅ 服务端音频有真实声音内容 → 问题在真狗端（音量/播放通路/状态）")
            else:
                print("❌ 音频几乎是静音 → 服务端 TTS 链路问题")
    except Exception as e:  # noqa: BLE001
        print("解码失败（opus 库问题）:", e)


asyncio.run(main())
