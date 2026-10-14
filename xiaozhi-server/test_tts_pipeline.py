"""离线验证：EdgeTTS 文本合成 + opus 编码（狗发声链路的音频生成环节）。
不依赖物理狗，只验证服务端能产出狗喇叭要的 opus 音频帧。
"""
import asyncio
import sys
import os

# opuslib_next 需要 libopus.dll 在 PATH
os.environ["PATH"] = r"D:\Anaconda\envs\xiaozhi\Library\bin" + os.pathsep + os.environ.get("PATH", "")

import edge_tts
from io import BytesIO
from pydub import AudioSegment
from opuslib_next import Encoder


async def synth_to_opus(text: str, out_path: str):
    # 1) EdgeTTS 合成到内存 mp3
    communicate = edge_tts.Communicate(text, voice="zh-CN-XiaoxiaoNeural")
    mp3_buf = BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_buf.write(chunk["data"])
    mp3_buf.seek(0)
    print(f"[1] EdgeTTS 合成完成，mp3 字节数 = {len(mp3_buf.getvalue())}")

    # 2) pydub 转 16k 单声道 PCM（与服务端 speak_text 一致）
    audio = AudioSegment.from_file(mp3_buf, format="mp3")
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    pcm = audio.raw_data
    print(f"[2] PCM 16k/mono 字节数 = {len(pcm)}")

    # 3) opus 编码为帧（FRAME_DURATION=60ms，与设备期望一致）
    enc = Encoder(16000, 1, "voip")
    enc.bitrate = 32000
    frame_size = int(16000 * 60 / 1000)  # 960 samples/frame
    frames = [pcm[i:i + frame_size * 2] for i in range(0, len(pcm), frame_size * 2)]
    opus_frames = []
    for fr in frames:
        opus_frames.append(enc.encode(fr, frame_size))
    with open(out_path, "wb") as f:
        for of in opus_frames:
            f.write(of)
    print(f"[3] opus 帧数 = {len(opus_frames)}，已写入 {out_path} ({os.path.getsize(out_path)} bytes)")
    return len(opus_frames)


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "女儿提醒您：记得按时吃药"
    out = sys.argv[2] if len(sys.argv) > 2 else "test_dog_speak.opus"
    n = asyncio.run(synth_to_opus(text, out))
    print(f"\n✅ TTS+opus 管线可用，共 {n} 帧。狗连上 WS 后将收到等价的音频流。")
