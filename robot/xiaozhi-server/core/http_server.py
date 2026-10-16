import asyncio
import json
from aiohttp import web
from config.logger import setup_logging
from core.api.ota_handler import OTAHandler
from core.api.vision_handler import VisionHandler
from core.device_registry import get_device, online_device_ids

TAG = __name__


class SimpleHttpServer:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()
        self.ota_handler = OTAHandler(config)
        self.vision_handler = VisionHandler(config)

    def _get_websocket_url(self, local_ip: str, port: int) -> str:
        """获取websocket地址

        Args:
            local_ip: 本地IP地址
            port: 端口号

        Returns:
            str: websocket地址
        """
        server_config = self.config["server"]
        websocket_config = server_config.get("websocket")

        if websocket_config and "你" not in websocket_config:
            return websocket_config
        else:
            return f"ws://{local_ip}:{port}/xiaozhi/v1/"

    async def list_devices(self, request: web.Request):
        """列出当前已连接的设备：GET /devices"""
        return web.json_response(
            {
                "online_devices": online_device_ids(),
                "count": len(online_device_ids()),
            }
        )

    async def say_to_device(self, request: web.Request):
        """主动让指定设备朗读文本：POST /devices/{device_id}/say {text: str}"""
        device_id = request.match_info["device_id"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)

        text = (body or {}).get("text", "")
        if not text or not str(text).strip():
            return web.json_response({"error": "missing 'text'"}, status=400)

        handler = get_device(device_id)
        if handler is None:
            return web.json_response(
                {
                    "error": "device not connected",
                    "device_id": device_id,
                    "online_devices": online_device_ids(),
                },
                status=404,
            )

        try:
            # 关键修复（2026-10-16）：设备只有收到 {"type":"tts","state":"start"} 才会
            # 从 listening 切换到 speaking 状态并开启音频输出。正常对话路径由
            # send_stt_message 发送此消息，而 say 路径绕过了 STT，导致设备一直停在
            # listening（日志可见它持续上报 listen start auto），把下发的音频帧当回声丢弃。
            await handler.websocket.send(
                json.dumps(
                    {"type": "tts", "state": "start", "session_id": handler.session_id}
                )
            )
            handler.client_is_speaking = True
            await asyncio.sleep(0.15)  # 给固件一点时间切换状态机
            ok = handler.speak_text(text)
        except Exception as e:  # noqa: BLE001
            self.logger.bind(tag=TAG).error(f"下发朗读失败: {e}")
            return web.json_response({"error": str(e)}, status=500)

        if not ok:
            return web.json_response(
                {"error": "tts not ready, please retry later"}, status=409
            )

        return web.json_response(
            {"status": "ok", "device_id": device_id, "text": text}
        )

    async def call_device_tool(self, request: web.Request):
        """调试用：直接调用设备端暴露的 MCP 工具（2026-10-16 加）。

        POST /devices/{device_id}/tool  {"name": "self.get_device_status", "arguments": {}}
        典型用途：查设备真实状态（音量/电池/网络）、用官方工具设音量
        （self.audio_speaker.set_volume，arguments {"volume": 0-100}）。
        绕过 LLM，仅用于排查"设备在线但不出声"这类问题。
        """
        device_id = request.match_info["device_id"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)

        name = str((body or {}).get("name") or "").strip()
        arguments = (body or {}).get("arguments") or {}
        if not name:
            return web.json_response({"error": "missing 'name'"}, status=400)

        handler = get_device(device_id)
        if handler is None:
            return web.json_response(
                {"error": "device not connected", "device_id": device_id,
                 "online_devices": online_device_ids()},
                status=404,
            )

        try:
            from core.providers.tools.device_mcp.mcp_executor import (
                DeviceMCPExecutor,
            )

            executor = DeviceMCPExecutor(handler)
            result = await executor.execute(handler, name, arguments)
            # 结果可能在 response（设备返回含 action 的 JSON）或 result（REQLLM 路径）
            text = (
                getattr(result, "response", None)
                or getattr(result, "result", None)
                or str(result)
            )
            self.logger.info(f"call_device_tool: {name} -> {str(text)[:200]}")
            return web.json_response({"status": "ok", "tool": name, "result": str(text)})
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"call_device_tool 失败: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def say_options(self, request: web.Request):        return web.Response(
            status=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    async def start(self):
        try:
            server_config = self.config["server"]
            read_config_from_api = self.config.get("read_config_from_api", False)
            host = server_config.get("ip", "0.0.0.0")
            port = int(server_config.get("http_port", 8003))

            if port:
                app = web.Application()

                if not read_config_from_api:
                    # 如果没有开启智控台，只是单模块运行，就需要再添加简单OTA接口，用于下发websocket接口
                    app.add_routes(
                        [
                            web.get("/xiaozhi/ota/", self.ota_handler.handle_get),
                            web.post("/xiaozhi/ota/", self.ota_handler.handle_post),
                            web.options(
                                "/xiaozhi/ota/", self.ota_handler.handle_options
                            ),
                            # 下载接口，仅提供 data/bin/*.bin 下载
                            web.get(
                                "/xiaozhi/ota/download/{filename}",
                                self.ota_handler.handle_download,
                            ),
                            web.options(
                                "/xiaozhi/ota/download/{filename}",
                                self.ota_handler.handle_options,
                            ),
                        ]
                    )
                # 添加路由
                app.add_routes(
                    [
                        web.get("/mcp/vision/explain", self.vision_handler.handle_get),
                        web.post(
                            "/mcp/vision/explain", self.vision_handler.handle_post
                        ),
                        web.options(
                            "/mcp/vision/explain", self.vision_handler.handle_options
                        ),
                        # 主动让已连接的设备朗读指定文本（绕过 LLM）
                        web.get("/devices", self.list_devices),
                        web.post(
                            "/devices/{device_id}/say", self.say_to_device
                        ),
                        web.options(
                            "/devices/{device_id}/say", self.say_options
                        ),
                        # 调试用：直接调用设备端 MCP 工具（2026-10-16 加，
                        # 用于查/设音量等设备状态，如 self.get_device_status）
                        web.post(
                            "/devices/{device_id}/tool", self.call_device_tool
                        ),
                    ]
                )

                # 运行服务
                runner = web.AppRunner(app)
                await runner.setup()
                site = web.TCPSite(runner, host, port)
                await site.start()

                # 保持服务运行
                while True:
                    await asyncio.sleep(3600)  # 每隔 1 小时检查一次
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"HTTP服务器启动失败: {e}")
            import traceback

            self.logger.bind(tag=TAG).error(f"错误堆栈: {traceback.format_exc()}")
            raise
