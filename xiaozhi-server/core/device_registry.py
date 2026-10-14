"""已连接设备注册表（按 device_id 索引 ConnectionHandler）。

xiaozhi-server 原本在 ``_handle_connection`` 里每来一个设备就 new 一个
``ConnectionHandler``，处理完即弃，外部（HTTP 路由）拿不到任何设备引用，
因此无法实现「服务端主动给某台设备推一句话」。

本模块用一个进程内全局字典填补这个缺口。WebSocket 服务与 HTTP(aiohttp)
服务都由 ``app.py`` 在同一进程 / 同一事件循环里启动，所以模块级字典是安全的。
"""

from typing import Dict, Optional

# device_id -> ConnectionHandler 实例
connected_devices: Dict[str, object] = {}


def register_device(device_id: Optional[str], handler) -> None:
    """设备连接建立后登记。"""
    if device_id:
        connected_devices[device_id] = handler


def unregister_device(device_id: Optional[str]) -> None:
    """设备断开后注销。"""
    if device_id:
        connected_devices.pop(device_id, None)


def get_device(device_id: Optional[str]):
    """按 device_id 取回 ConnectionHandler；不在线返回 None。"""
    if not device_id:
        return None
    return connected_devices.get(device_id)


def online_device_ids() -> list:
    """当前在线设备 id 列表。"""
    return list(connected_devices.keys())
