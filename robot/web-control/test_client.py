"""模拟前端连接流程，验证 hello 握手 + listen/detect 文本通道 → robot_action。"""
import asyncio, json, websockets

WS = "ws://127.0.0.1:8001/xiaozhi/v1/?device-id=web-test-001&client-id=web-test-001"

async def main():
    async with websockets.connect(WS) as ws:
        await ws.send(json.dumps({
            "type": "hello", "version": 1, "transport": "websocket",
            "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
        }))
        print(">> hello 已发送")

        async def reader():
            async for m in ws:
                if isinstance(m, bytes):
                    print(f"<< [二进制音频 {len(m)}字节]")
                else:
                    print("<<", m)

        rtask = asyncio.create_task(reader())
        await asyncio.sleep(2)  # 等 welcome + 后台初始化

        print(">> 发送指令: 握手")
        await ws.send(json.dumps({"type": "listen", "state": "detect", "mode": "manual", "text": "握个手"}))

        await asyncio.sleep(8)  # 等 LLM + 工具调用 + TTS
        rtask.cancel()

asyncio.run(main())
