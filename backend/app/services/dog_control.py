"""机器狗动作控制：直接调 ESP-Hi 固件的 HTTP /control 接口。

协议与小智端 plugins_func/functions/robot_action.py 一致：
- action 类：预置姿势，一次性执行（如 {"action": "7"} 握手）
- move 类：持续运动，必须限时后补发停止 {"move": "S"}
"""
import asyncio
import logging
from typing import Any, Dict, List, Tuple

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# 动作名 -> /control 请求体（来源：ESP-Hi 固件实测接口）
ACTION_MAP: Dict[str, Dict[str, str]] = {
    "前进": {"move": "F"},
    "后退": {"move": "B"},
    "左转": {"move": "L"},
    "右转": {"move": "R"},
    "鞠躬": {"action": "2"},
    "摇摆": {"action": "4"},
    "握手": {"action": "7"},
    "戳戳": {"action": "8"},
    "伸懒腰": {"action": "9"},
    "前跳": {"action": "10"},
    "收腿": {"action": "12"},
}

# vision-control Action.key -> 中文动作名（和 ACTION_MAP 对齐）
KEY_MAP: Dict[str, str] = {
    "walk_forward": "前进",
    "walk_back": "后退",
    "turn_left": "左转",
    "turn_right": "右转",
    "stop": "停止",
    "sit": "鞠躬",
    "stand": "握手",
    "stretch": "伸懒腰",
    "shake": "摇摆",
}

MOVE_ACTIONS = {"前进", "后退", "左转", "右转"}

DEFAULT_MOVE_DURATION = 1.5
MAX_MOVE_DURATION = 3.0  # 老人场景比小智端更保守
STOP_PAYLOAD = {"move": "S"}
GAP_BETWEEN_ACTIONS = 0.4


def normalize_actions(raw: List[Any]) -> List[Tuple[str, float | None]]:
    """把 LLM 输出的动作列表清洗成 (动作名, 时长) 序列，过滤不认识的动作。

    安全约束：最多 2 个动作；移动类最多 1 个且时长封顶。
    """
    seq: List[Tuple[str, float | None]] = []
    for item in raw:
        name, dur = None, None
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("action")
            dur = item.get("duration")
        if name not in ACTION_MAP:
            continue
        if name in MOVE_ACTIONS and any(n in MOVE_ACTIONS for n, _ in seq):
            continue  # 移动类最多一个
        seq.append((name, dur))
        if len(seq) >= 2:
            break
    return seq


async def execute_actions(
    base_url: str, seq: List[Tuple[str, float | None]], timeout: float = 5.0
) -> bool:
    """依次执行动作序列。返回狗是否实际响应（离线时不抛异常）。"""
    if not seq:
        return True
    url = f"{base_url.rstrip('/')}/control"
    names = "、".join(n for n, _ in seq)
    logger.info("机器狗动作序列: %s -> %s", names, url)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=2.0)
        ) as client:
            for idx, (name, dur) in enumerate(seq):
                payload = ACTION_MAP[name]
                resp = await client.post(url, json=payload)
                logger.info("机器狗响应: %s <- %s", resp.status_code, payload)
                if "move" in payload:
                    move_time = dur if dur is not None else DEFAULT_MOVE_DURATION
                    move_time = max(0.3, min(float(move_time), MAX_MOVE_DURATION))
                    await asyncio.sleep(move_time)
                    await client.post(url, json=STOP_PAYLOAD)
                if idx < len(seq) - 1:
                    await asyncio.sleep(GAP_BETWEEN_ACTIONS)
    except httpx.HTTPError as e:
        logger.warning("机器狗未响应(%s)，指令已构造但未送达", e)
        return False
    return True


async def execute_stop(base_url: str, timeout: float = 5.0) -> bool:
    """发送停止指令（走 STOP_PAYLOAD），狗离线时不抛异常。"""
    url = f"{base_url.rstrip('/')}/control"
    logger.info("机器狗停止指令 -> %s", url)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=2.0)) as client:
            resp = await client.post(url, json=STOP_PAYLOAD)
            logger.info("机器狗停止响应: %s", resp.status_code)
    except httpx.HTTPError as e:
        logger.warning("机器狗未响应(%s)，停止指令未送达", e)
        return False
    return True


async def push_to_dog(text: str) -> bool:
    """把一句话推给当前已连接小智服务端的机器狗，让它开口念出来。

    返回 True 表示已成功下发朗读任务（不代表狗一定播放成功）。
    狗未连接 / 小智服务不可达时静默失败，不影响主流程。
    """
    settings = get_settings()
    # 从视觉地址推导出小智 HTTP 基址：http://127.0.0.1:8003/mcp/... -> http://127.0.0.1:8003
    base = settings.xiaozhi_vision_url.split("/mcp", 1)[0].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base}/devices")
            if r.status_code != 200:
                return False
            devices = (r.json() or {}).get("online_devices") or []
            if not devices:
                logger.info("push_to_dog: 当前没有已连接的狗设备，跳过发声")
                return False
            dev = devices[0]
            resp = await client.post(
                f"{base}/devices/{dev}/say",
                json={"text": text},
            )
            ok = resp.status_code == 200
            logger.info("push_to_dog -> device=%s ok=%s", dev, ok)
            return ok
    except Exception as e:  # noqa: BLE001
        logger.warning("push_to_dog 失败（狗未连或不可达）: %s", e)
        return False
