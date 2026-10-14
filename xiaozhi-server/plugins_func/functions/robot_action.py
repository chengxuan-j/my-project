"""机器狗动作控制工具：把狗的简单指令包装成 function_call 工具，由 LLM 自主决定何时调用。"""
import asyncio
import httpx
import ipaddress
import socket
from urllib.parse import urlparse

import psutil
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

# 移动时长默认值与上限（秒）。move 类指令是持续运动，必须限制时长后自动停止，
# 否则狗会一直走到收到停止指令为止。
DEFAULT_MOVE_DURATION = 1.5
MAX_MOVE_DURATION = 5.0
STOP_PAYLOAD = {"move": "S"}  # ESP-Hi 固件的停止指令

# 动作名 -> /control 请求体。来源：ESP-Hi 固件实测接口
# move 类：方向移动（持续，需补发停止）；action 类：预置姿势（一次性，无需停止）
ACTION_MAP = {
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

robot_action_function_desc = {
    "type": "function",
    "function": {
        "name": "robot_action",
        "description": (
            "控制机器狗做一个或一连串动作。当用户希望狗做动作、移动身体或用肢体表达情绪时调用。"
            "用户可能一句话要求多个连续动作（如“先向前走再向后退”“转个圈然后握手”），"
            "此时把它们按顺序全部放进 actions 列表，机器狗会依次执行。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "description": "要依次执行的动作序列，按用户描述的先后顺序排列。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "description": "要执行的动作",
                                "enum": list(ACTION_MAP.keys()),
                            },
                            "duration": {
                                "type": "number",
                                "description": (
                                    "仅移动类动作（前进/后退/左转/右转）有效：移动秒数，"
                                    f"默认 {DEFAULT_MOVE_DURATION}，最大 {MAX_MOVE_DURATION}。"
                                    "“走一点”给小值，“多走会”给较大值。"
                                ),
                            },
                        },
                        "required": ["action"],
                    },
                },
            },
            "required": ["actions"],
        },
    },
}


GAP_BETWEEN_ACTIONS = 0.4  # 相邻动作之间的间隔（秒），避免指令粘连


def _local_address_for_dog(base_url: str):
    """同网段设备走对应网卡，避开 Windows 上更具体的错误静态路由。"""
    try:
        target = ipaddress.ip_address(urlparse(base_url).hostname)
    except (TypeError, ValueError):
        return None
    if not isinstance(target, ipaddress.IPv4Address):
        return None

    matches = []
    for addresses in psutil.net_if_addrs().values():
        for address in addresses:
            if address.family != socket.AF_INET or not address.netmask:
                continue
            try:
                network = ipaddress.ip_network(
                    f"{address.address}/{address.netmask}", strict=False
                )
            except ValueError:
                continue
            if target in network:
                matches.append((network.prefixlen, address.address))
    return max(matches, default=(0, None))[1]


@register_function("robot_action", robot_action_function_desc, ToolType.SYSTEM_CTL)
async def robot_action(conn: "ConnectionHandler", actions=None, action: str = None, duration: float = None):
    # 兼容两种入参：新版 actions 列表；旧版单个 action（模型偶尔仍这么发）
    seq = []
    if actions:
        for item in actions:
            if isinstance(item, dict) and item.get("action"):
                seq.append((item["action"], item.get("duration")))
    elif action:
        seq.append((action, duration))

    if not seq:
        return ActionResponse(action=Action.RESPONSE, response="没听清要做什么动作")

    # 校验动作名，过滤不认识的
    unknown = [a for a, _ in seq if a not in ACTION_MAP]
    seq = [(a, d) for a, d in seq if a in ACTION_MAP]
    if not seq:
        return ActionResponse(
            action=Action.RESPONSE, response=f"我还不会「{unknown[0]}」这个动作"
        )

    base_url = conn.config.get("plugins", {}).get("robot_action", {}).get("base_url")
    if not base_url:
        return ActionResponse(action=Action.RESPONSE, response="机器狗地址还没配置")

    url = f"{base_url.rstrip('/')}/control"

    async def post(client, body):
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        logger.bind(tag=TAG).info(f"机器狗响应: {resp.status_code} <- {body}")

    names = "、".join(a for a, _ in seq)
    logger.bind(tag=TAG).info(f"机器狗动作序列: {names} -> {url}")
    try:
        source_ip = _local_address_for_dog(base_url)
        transport = (
            httpx.AsyncHTTPTransport(local_address=source_ip, trust_env=False)
            if source_ip
            else None
        )
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=2.0),
            trust_env=False,
            transport=transport,
        ) as client:
            for idx, (act, dur) in enumerate(seq):
                payload = ACTION_MAP[act]
                logger.bind(tag=TAG).info(f"执行动作: {act} {payload}")
                await post(client, payload)
                # move 类为持续运动，移动一段时间后补发停止
                if "move" in payload:
                    move_time = dur if dur is not None else DEFAULT_MOVE_DURATION
                    move_time = max(0.3, min(float(move_time), MAX_MOVE_DURATION))
                    await asyncio.sleep(move_time)
                    await post(client, STOP_PAYLOAD)
                # 动作之间留个间隔（最后一个不用等）
                if idx < len(seq) - 1:
                    await asyncio.sleep(GAP_BETWEEN_ACTIONS)
    except httpx.HTTPError as e:
        logger.bind(tag=TAG).warning(f"机器狗动作未完成({e})")
        return ActionResponse(
            action=Action.RESPONSE,
            response="机器狗未响应，动作未完成。请确认设备在线且地址正确。",
        )

    return ActionResponse(action=Action.RECORD, result="done", response=f"好的，我来{names}")
