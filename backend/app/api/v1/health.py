"""健康检查。"""
from fastapi import APIRouter

from app.core.container import get_qwen_client

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    client = get_qwen_client()
    return {
        "status": "ok",
        "model": client.model,
        "api_configured": client.is_configured,
    }
