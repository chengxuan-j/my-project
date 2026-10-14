"""
指令下发层。

默认只往控制台打印将要发送的 MCP 报文（dry-run），方便在固件还没改的时候
先把识别准确率调好。等设备端接上本地 WebSocket 通道后，加 --ws ws://<狗IP>:8080/ws
就能真的驱动机器狗。

报文格式严格对齐 main/mcp_server.cc 的 ParseMessage()：
  - 顶层必须有 "jsonrpc":"2.0"（字符串）
  - "method" 为 "tools/call"
  - "params.name" 为工具名，"params.arguments" 为对象
  - "id" 必须是**数字**，固件里用 cJSON_IsNumber 校验，传字符串会被直接丢弃
  - arguments 的键名必须和 eda_dog_controller.cc 里 Property(...) 的名字一致
"""

import json
import time
from typing import Any, Dict, Optional

from action_rules import Action


def build_tools_call(action: Action, seq: int) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": seq,
        "method": "tools/call",
        "params": {"name": action.tool, "arguments": dict(action.args)},
    }


class BaseEmitter:
    def emit(self, action: Action, seq: int) -> None:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError

    def close(self) -> None:
        pass


class DryRunEmitter(BaseEmitter):
    """只打印报文，不发送。"""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def describe(self) -> str:
        return "dry-run（仅打印报文，未连接设备）"

    def emit(self, action: Action, seq: int) -> None:
        payload = build_tools_call(action, seq)
        if not self.verbose:
            return
        print(f"\n[{time.strftime('%H:%M:%S')}] #{seq} {action.label} ← {action.hint}")
        print("  发送报文: " + json.dumps(payload, ensure_ascii=False))
        if action.tool != "self.dog.stop":
            print("  （等待设备空闲后才能发下一条，对应固件的动作队列是阻塞式的）")


class WebSocketEmitter(BaseEmitter):
    """连到设备上的本地 WebSocket 控制服务（websocket_control_server）。"""

    def __init__(self, url: str, timeout: float = 3.0):
        self.url = url
        self.timeout = timeout
        self._ws: Optional[Any] = None
        self._last_error: Optional[str] = None

    def describe(self) -> str:
        if self._ws is not None:
            return f"已连接 {self.url}"
        if self._last_error:
            return f"未连接 {self.url}（{self._last_error}）"
        return f"待连接 {self.url}"

    def _ensure(self) -> bool:
        if self._ws is not None:
            return True
        try:
            import websocket  # websocket-client，可选依赖
        except ImportError:
            self._last_error = "缺少 websocket-client，请 pip install websocket-client"
            return False
        try:
            self._ws = websocket.create_connection(self.url, timeout=self.timeout)
            self._last_error = None
            return True
        except Exception as exc:  # noqa: BLE001 - 连接失败原因很多，统一降级
            self._ws = None
            self._last_error = str(exc)
            return False

    def emit(self, action: Action, seq: int) -> None:
        if not self._ensure():
            print(f"  发送失败：{self._last_error}")
            return
        payload = build_tools_call(action, seq)
        try:
            self._ws.send(json.dumps(payload, ensure_ascii=False))
            self._ws.settimeout(self.timeout)
            reply = self._ws.recv()
            print(f"  设备回复: {reply}")
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            print(f"  发送失败：{exc}")
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None


class HttpEmitter(BaseEmitter):
    """向 ESP-Hi 机器狗发送 HTTP /control 报文（对齐 robot_action.py 的映射逻辑）。

    把视觉侧的 Action.key 翻译成 ESP-Hi 固件能懂的 {"move":"..."} 或 {"action":"..."}。
    move 类为持续运动，发送后 1.5s 自动补发停止指令 {"move":"S"}。

    映射表对齐 main/xiaozhi-server/plugins_func/functions/robot_action.py L22-34。
    """

    # Action.key -> ESP-Hi /control 请求体
    ACTION_MAP = {
        "walk_forward": {"move": "F"},  # 前进
        "turn_left": {"move": "L"},     # 左转
        "turn_right": {"move": "R"},    # 右转
        "stop": {"move": "S"},          # 停止
        "sit": {"action": "2"},         # 鞠躬（原"坐下"，ESP-Hi无，映射到鞠躬）
        "stand": {"action": "7"},       # 握手（原"站立"，ESP-Hi无，映射到握手）
        "stretch": {"action": "9"},     # 伸懒腰
        "shake": {"action": "4"},       # 摇摆
    }

    MOVE_DURATION = 1.5  # move 类持续时长（秒）
    STOP_PAYLOAD = {"move": "S"}

    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session: Optional[Any] = None
        self._last_error: Optional[str] = None

    def describe(self) -> str:
        status = "已连接" if self._last_error is None else f"未连接（{self._last_error}）"
        return f"HTTP {self.base_url}/control ({status})"

    def _ensure_session(self) -> Any:
        if self._session is None:
            try:
                import httpx
                self._session = httpx.Client(timeout=httpx.Timeout(self.timeout, connect=2.0))
            except ImportError:
                raise RuntimeError("缺少 httpx，请 pip install httpx")
        return self._session

    def emit(self, action: Action, seq: int) -> None:
        key = action.key
        if key not in self.ACTION_MAP:
            print(f"  跳过未映射动作: {key}")
            return

        payload = self.ACTION_MAP[key]
        url = f"{self.base_url}/control"

        try:
            client = self._ensure_session()
            print(f"\n[{time.strftime('%H:%M:%S')}] #{seq} {action.label} ← {action.hint}")
            print(f"  POST {url} {json.dumps(payload, ensure_ascii=False)}")

            resp = client.post(url, json=payload)
            print(f"  狗响应: {resp.status_code}")
            self._last_error = None

            # move 类持续运动，1.5s 后补发停止
            if "move" in payload and payload["move"] != "S":
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                async def delayed_stop():
                    await asyncio.sleep(self.MOVE_DURATION)
                    try:
                        stop_resp = client.post(url, json=self.STOP_PAYLOAD)
                        print(f"  自动停止: {stop_resp.status_code}")
                    except Exception as e:
                        print(f"  自动停止失败: {e}")

                loop.create_task(delayed_stop())

        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            print(f"  发送失败: {exc}")

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:  # noqa: BLE001
                pass
            self._session = None
