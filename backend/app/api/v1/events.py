"""SSE（Server-Sent Events）实时推送端点。

EventSource 无法自定义请求头，因此 token 通过 query 参数传入。
"""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.core.events import bus
from app.core.security import TOKEN_TYPE_ACCESS, try_decode

router = APIRouter(tags=["events"])

HEARTBEAT_SECONDS = 20


@router.get("/events/stream")
async def events_stream(request: Request, token: str = ""):
    """订阅当前账号的实时事件流。"""
    payload = try_decode(token, expected_type=TOKEN_TYPE_ACCESS)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token 无效或已过期"
        )
    user_id = payload.get("sub", "")
    queue = bus.subscribe(user_id)

    async def gen():
        try:
            # 首帧：告知已连接
            yield "event: connected\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # 注释帧心跳，防代理超时
                    continue
                etype = event.get("type", "message")
                yield f"event: {etype}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            bus.unsubscribe(user_id, queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 提示 Nginx 不要缓冲
        },
    )
