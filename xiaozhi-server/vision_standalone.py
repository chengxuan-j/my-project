# -*- coding: utf-8 -*-
"""MCP Vision 协议兼容的独立视觉服务（小智全量环境的临时替代）。

背景：D:/Anaconda/envs/xiaozhi conda 环境被删除，完整 app.py 无法启动。
本服务只实现 elderly_companion 用到的 `/mcp/vision/explain` 接口，
协议与 xiaozhi-esp32-server 的 VisionHandler 一致：
  GET  /mcp/vision/explain  -> 状态文本
  POST /mcp/vision/explain  -> multipart(question, 图片文件)
     响应 {"success": true, "action": "RESPONSE", "response": "描述文本"}

视觉模型：dashscope OpenAI 兼容接口 qwen-vl-max（key 读 elderly_companion/.env）。
用 elderly_companion/.venv 的 python 运行：python vision_standalone.py
"""
import base64
import os

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

MAX_FILE_SIZE = 5 * 1024 * 1024
PORT = 8003

# 图片魔数（与 xiaozhi is_valid_image_file 对齐的常见格式）
MAGIC = {
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG": "png",
    b"GIF8": "gif",
    b"BM": "bmp",
    b"RIFF": "webp",  # RIFF....WEBP
}


def read_llm_config():
    """从 elderly_companion/.env 读 dashscope 配置。"""
    env_path = r"E:/elderly_companion/.env"
    cfg = {}
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("QWEN_API_KEY="):
                cfg["api_key"] = line.split("=", 1)[1]
            elif line.startswith("QWEN_BASE_URL="):
                cfg["base_url"] = line.split("=", 1)[1]
    cfg.setdefault("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    cfg["model"] = "qwen-vl-max"
    return cfg


app = FastAPI(title="xiaozhi vision standalone")


@app.get("/mcp/vision/explain")
async def explain_get():
    return PlainTextResponse(
        f"MCP Vision 接口运行正常（standalone 模式），视觉解释接口地址是：http://127.0.0.1:{PORT}/mcp/vision/explain"
    )


@app.post("/mcp/vision/explain")
async def explain_post(request: Request):
    try:
        form = await request.form()
        question = str(form.get("question") or "").strip()
        upload = form.get("file")
        if not question:
            return JSONResponse({"success": False, "message": "缺少问题字段"})
        if upload is None:
            return JSONResponse({"success": False, "message": "缺少图片文件"})

        image_data = await upload.read()
        if not image_data:
            return JSONResponse({"success": False, "message": "图片数据为空"})
        if len(image_data) > MAX_FILE_SIZE:
            return JSONResponse({"success": False, "message": "图片大小超过限制，最大允许5.0MB"})
        if not any(image_data.startswith(m) for m in MAGIC):
            return JSONResponse({"success": False, "message": "不支持的文件格式"})

        cfg = read_llm_config()
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        question = question + "(请使用中文回复)"

        payload = {
            "model": cfg["model"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            },
                        },
                    ],
                }
            ],
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{cfg['base_url']}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
            )
        if resp.status_code != 200:
            return JSONResponse(
                {"success": False, "message": f"视觉模型调用失败 HTTP {resp.status_code}"}
            )
        result = resp.json()["choices"][0]["message"]["content"]
        return JSONResponse(
            {"success": True, "action": "RESPONSE", "response": result}
        )
    except Exception as e:
        return JSONResponse({"success": False, "message": f"处理请求时发生错误: {e}"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
