"""机器狗动作控制：直接调 ESP-Hi 固件的 HTTP /control 接口。

协议与小智端 plugins_func/functions/robot_action.py 一致：
- action 类：预置姿势，一次性执行（如 {"action": "7"} 握手）
- move 类：持续运动，必须限时后补发停止 {"move": "S"}
"""
import asyncio
import logging
from typing import Any, Dict, List, Tuple

import httpx

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
