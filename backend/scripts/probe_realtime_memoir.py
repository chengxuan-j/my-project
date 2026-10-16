# -*- coding: utf-8 -*-
"""实时回忆模式端到端探针（2026-10-15）。

三条路径：
A. 不带回忆关键词 → 不触发（不调 LLM，秒回）
B. 命中关键词 + 是平生故事 → archived + family 记档 + 推送调用
C. 命中关键词 + 创伤基调 → private 锁定，不推送

跑完打印 life_stories 最新几行；测试数据由调用方按 id 清理。
"""
import asyncio
import os
import sys

sys.path.insert(0, "E:/elderly_companion/backend")
os.chdir("E:/elderly_companion/backend")

from app.api.v1.chat import _extract_and_save_story  # noqa: E402
from app.memoir import recall_keywords  # noqa: E402
from app.memoir.story_extractor import StoryExtractor  # noqa: E402


async def main():
    print("== A. 关键词快筛 ==")
    print("  命中:", recall_keywords.matched_word("以前在纺织厂上班的时候，三班倒真苦"))
    print("  未命中:", repr(recall_keywords.matched_word("今天天气真不错，想出去遛弯")))

    ex = StoryExtractor()

    print("== B. 命中 + 平生故事（elderly_001 王阿姨）==")
    await _extract_and_save_story(
        ex, "elderly_001",
        "以前在纺织厂上班的时候，三班倒真苦，手上全是茧子",
        "阿姨，那时候真不容易，您坚持了十几年呢",
    )

    print("== C. 命中 + 创伤基调（应锁 private）==")
    await _extract_and_save_story(
        ex, "elderly_001",
        "以前地震那年，老伴没能出来，这事儿我从没跟人讲过",
        "阿姨，不想说就别说了，我陪着您",
    )


asyncio.run(main())

import sqlite3  # noqa: E402

con = sqlite3.connect("file:E:/elderly_companion/storage/companion.db?mode=ro", uri=True)
print("== life_stories 最新 5 行 ==")
for r in con.execute(
    "select id, user_id, substr(title,1,18), status, visibility, visibility_locked, "
    "avoid_flag, place, people from life_stories order by id desc limit 5"
):
    print(" ", r)
con.close()
