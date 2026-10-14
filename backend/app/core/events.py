"""进程内事件总线：供 SSE 实时推送使用。

- 按 user_id 维护订阅队列；publish 时推给该用户的所有连接。
- 注意：仅进程内有效。若上线用多 worker / 多实例，请替换为 Redis pub/sub
  （把 subscribe/publish 换成 Redis 频道即可，接口保持不变）。
"""
import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._subs: Dict[str, Set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, user_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subs[user_id].add(q)
        logger.info("sse_subscribe user=%s conns=%d", user_id, len(self._subs[user_id]))
        return q

    def unsubscribe(self, user_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(user_id)
        if subs and q in subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(user_id, None)
        logger.info("sse_unsubscribe user=%s", user_id)

    def publish(self, user_id: str, event: Dict[str, Any]) -> None:
        """向某用户的所有连接推送事件；非阻塞，队列满时丢弃最旧的一条。"""
        for q in list(self._subs.get(user_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass


bus = EventBus()
