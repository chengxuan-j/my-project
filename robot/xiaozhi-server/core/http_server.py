import asyncio
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

    async def say_options(self, request: web.Request):
        return web.Response(
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
