# -*- coding: utf-8 -*-
"""预生成（"边说边算"）缓存。

动机：老人说完话后，前置（分析 + 检索）约 1.1s、生成首 token 约 0.4s，
这段时间是**纯等**出来的。若能在老人还在说话时就先用部分识别结果把它算好，
停下时几乎可以立刻出声。

安全性（不牺牲质量）：
- 只有当**最终识别文本**与"预生成所用文本"匹配时才复用：
  完全相同，或最终文本以预生成文本开头且覆盖比例 ≥ PREFIX_COVER_RATIO。
- 不匹配就走正常链路，只是白跑一次预生成（只多花算力，不影响回复正确性）。
- 预生成结果有 TTL，且被消费一次后即移除，避免长期占用内存/串话。

实现上有意保持轻量：纯内存字典 + asyncio 任务，进程重启即清空。
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# 预生成结果的有效期（秒）
TTL_SECONDS = 90.0
# 太短的文本预生成价值低、命中率也差
MIN_CHARS = 6
# 前缀命中时，预生成文本至少要覆盖最终文本的这个比例
PREFIX_COVER_RATIO = 0.7

_cache: Dict[str, Dict[str, Any]] = {}
_tasks: Dict[str, asyncio.Task] = {}
# 每个用户只保留一条在跑的预生成：部分识别结果每 2 秒就来一次，
# 若任由它们并发，三四条生成会一起抢 Qwen 配额，正式的 /chat/stream
# 反而排在后面——体感就是"说话停顿后要等很久才出声"。
_user_tasks: Dict[str, asyncio.Task] = {}

_PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:~·…—\-\u3000]+")


def normalize(text: str) -> str:
    """规范化：去掉空白与标点，只比较实义字符（ASR 标点不稳定）。"""
    return _PUNCT_RE.sub("", text or "")


def _ck(user_id: str, text: str) -> str:
    """缓存键：按用户隔离，避免不同老人同一句话互相串用。"""
    return f"{user_id}::{normalize(text)}"


def _purge(now: float) -> None:
    for k in [k for k, v in _cache.items() if now - v["ts"] > TTL_SECONDS]:
        _cache.pop(k, None)


def lookup(user_id: str, message: str) -> Optional[Dict[str, Any]]:
    """按最终文本找可复用的预生成结果（不消费）。"""
    key = _ck(user_id, message)
    if len(key) <= len(user_id) + 2:
        return None
    now = time.time()
    _purge(now)

    exact = _cache.get(key)
    if exact is not None and now - exact["ts"] <= TTL_SECONDS:
        logger.info("预生成命中（完全一致）len=%d", len(key))
        return exact

    best: Optional[Tuple[str, Dict[str, Any]]] = None
    for k, v in _cache.items():
        if now - v["ts"] > TTL_SECONDS or not k.startswith(f"{user_id}::"):
            continue
        if key.startswith(k) and len(k) >= len(key) * PREFIX_COVER_RATIO:
            if best is None or len(k) > len(best[0]):
                best = (k, v)
    if best is not None:
        logger.info(
            "预生成命中（前缀覆盖 %.0f%%）", 100.0 * len(best[0]) / max(len(key), 1)
        )
        return best[1]
    return None


def take(user_id: str, message: str) -> Optional[Dict[str, Any]]:
    """取出可复用的预生成结果，并把它从缓存移除（一次即弃）。"""
    item = lookup(user_id, message)
    if item is not None:
        _cache.pop(_ck(user_id, item.get("message", "")), None)
    return item


async def speculate(user_id: str, message: str) -> bool:
    """为 message 预生成回复。幂等：同一条文本在跑或已缓存时不重复触发。"""
    key = _ck(user_id, message)
    if len(key) <= len(user_id) + 2 or len(normalize(message)) < MIN_CHARS:
        return False
    if key in _cache and time.time() - _cache[key]["ts"] <= TTL_SECONDS:
        return True
    running = _tasks.get(key)
    if running is not None and not running.done():
        return True

    # 同一用户只保留最新一条：新的部分识别结果更接近最终文本，
    # 旧的预生成已经没用了，取消它，把算力让给新的和正式请求。
    prev = _user_tasks.get(user_id)
    if prev is not None and not prev.done():
        prev.cancel()

    task: Optional[asyncio.Task] = None

    async def _run() -> None:
        # 延迟导入避免循环依赖（companion_agent 也会 import 本模块的场景）
        from app.agent import companion_agent

        try:
            prepared = await companion_agent.prepare(user_id, message)
            chunks = []
            async for piece in companion_agent.stream_reply(
                user_id, message, prepared["context"]
            ):
                chunks.append(piece)
            reply = "".join(chunks).strip()
            if reply:
                _cache[key] = {
                    "reply": reply,
                    "context": prepared["context"],
                    "analysis": prepared["analysis"],
                    "message": message,
                    "ts": time.time(),
                }
                logger.info("预生成完成 len=%d reply=%s", len(key), reply[:30])
        except asyncio.CancelledError:
            logger.info("预生成已取消 len=%d", len(key))
            raise
        except Exception:  # noqa: BLE001  预生成失败绝不能影响正常链路
            logger.exception("预生成失败 len=%d", len(key))
        finally:
            # 只清理自己：期间可能已经换成了更新的一条
            if _tasks.get(key) is task:
                _tasks.pop(key, None)
            if _user_tasks.get(user_id) is task:
                _user_tasks.pop(user_id, None)

    task = asyncio.create_task(_run())
    _tasks[key] = task
    _user_tasks[user_id] = task
    logger.info("已接受预生成请求 len=%d", len(key))
    return True


def abort(user_id: str) -> None:
    """正式请求开始时调用：取消该用户还在跑的预生成，别和真回复抢配额。"""
    task = _user_tasks.pop(user_id, None)
    if task is not None and not task.done():
        task.cancel()
        logger.info("预生成让路：正式请求开始 user=%s", user_id)
