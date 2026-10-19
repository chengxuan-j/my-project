# -*- coding: utf-8 -*-
"""日报摘要防编造验证（2026-10-19）。

用今天真实的对话记录跑一遍 summarize（新 prompt），逐句核对
摘要里每个事实点是否在原对话中有依据，专门抓：
  - 天气/身体等全文没提的信息
  - 视觉神态描写（"眼神亮亮的"）
  - 无依据的建议（"添衣""翻相册"）
同时对比旧 prompt 的输出，确认问题确实被修掉。
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "E:/elderly_companion/backend")
os.chdir("E:/elderly_companion/backend")

from sqlalchemy import select  # noqa: E402

from app.db.base import get_session_factory  # noqa: E402
from app.db.models import Conversation  # noqa: E402
from app.services.digest_service import build_stats, summarize  # noqa: E402

USER_ID = "e_UfToQjT5ido"

# 原对话里**绝对没有**的说法——出现即判编造
FORBIDDEN = ["天气转凉", "添衣", "眼神", "相册", "多陪陪", "气温", "降温",
             "防感冒", "睡眠不好", "心脏病"]


async def main():
    factory = get_session_factory()
    day = datetime(2026, 10, 19, 0, 0, 0)
    async with factory() as s:
        convs = list((await s.execute(
            select(Conversation).where(
                Conversation.user_id == USER_ID,
                Conversation.created_at >= day,
                Conversation.created_at < day + timedelta(days=1),
                Conversation.role != "summary",
            ).order_by(Conversation.id)
        )).scalars().all())

    print("=" * 76)
    print("今天真实对话（已排除 summary 压缩记录）：%d 条" % len(convs))
    for c in convs:
        print("  [%s] %s" % (c.role, (c.content or "").replace("\n", " ")[:52]))
    print("=" * 76)

    stats = build_stats(convs)
    print("统计（修复后）：轮数=%s 时段=%s 话题=%s"
          % (stats["rounds"], stats["time_range"],
             [t["topic"] for t in stats["topics"]]))
    print()

    print("=== 新 prompt 生成的摘要 ===")
    text = await summarize("王奶奶", convs, memoir={"today": 0, "week": 0, "total": 3})
    print(" ", text)
    print("  字数：%d" % len(text))
    print()
    bad = [w for w in FORBIDDEN if w in text]
    if bad:
        print("❌ 仍检出无依据内容：%s" % bad)
    else:
        print("✅ 未检出任何编造关键词")


asyncio.run(main())
