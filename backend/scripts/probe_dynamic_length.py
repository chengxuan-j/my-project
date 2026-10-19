# -*- coding: utf-8 -*-
"""动态回复长度验证（2026-10-19）。

两部分：
1. 分档逻辑单测：构造不同 intent/emotion/risk/消息长度，核对落在哪一档
2. 真实链路实测：跑几句典型老人话语，记录实际回复字数与耗时
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, "E:/elderly_companion/backend")
os.chdir("E:/elderly_companion/backend")

from app.agent.companion_agent import (  # noqa: E402
    REPLY_TOKENS_LONG,
    REPLY_TOKENS_MEDIUM,
    REPLY_TOKENS_SHORT,
    reply_max_tokens,
)

LABEL = {REPLY_TOKENS_SHORT: "短(80)", REPLY_TOKENS_MEDIUM: "中(150)",
         REPLY_TOKENS_LONG: "长(240)"}

# (说明, 消息, context字段)
CASES = [
    ("寒暄", "你好呀", {"intent": "greeting"}),
    ("提醒吃药", "该吃药了", {"intent": "reminder"}),
    ("点歌", "放首老歌", {"intent": "music_request"}),
    ("危机(自伤)", "我不想活了", {"risk_level": "high", "intent": "safety_alert"}),
    ("危机但判成闲聊", "我不想活了", {"risk_level": "high", "intent": "casual_chat"}),
    ("要听故事", "给我讲个故事吧", {"intent": "story_request"}),
    ("问是否记得", "你还记得我女儿吗", {"intent": "memory_recall"}),
    ("讲往事(情绪怀旧)", "想起以前在厂里的事", {"emotion": "nostalgic"}),
    ("日常闲聊(短)", "今天天气不错", {"intent": "casual_chat"}),
    ("日常闲聊(长)", "昨天女儿带孙子来看我，我们一起去公园转了转，还买了点菜，挺开心的",
     {"intent": "casual_chat"}),
    ("倾诉且情绪强烈", "我心里难受得很，没人陪我说话", {"emotion": "lonely", "emotion_intensity": 0.9}),
    ("生气且情绪强烈", "气死我了，真是太过分了", {"emotion": "angry", "emotion_intensity": 0.9}),
    ("情感倾诉意图", "我想跟你说说话，心里挺难受的", {"intent": "emotional_sharing"}),
    ("倾诉但情绪平缓", "有点闷", {"emotion": "lonely", "emotion_intensity": 0.4}),
    ("问问题", "明天会下雨吗", {"intent": "question"}),
    ("说身体不舒服", "血压有点高", {"intent": "health_concern"}),
]

# 真实链路实测用例（消息, 说明）
LIVE = [
    ("你好呀", "寒暄→应短"),
    ("给我讲个故事吧", "故事→应长"),
    ("想起以前在纺织厂上班的日子，三班倒真不是人干的", "怀旧→应长"),
    ("今天天气不错，出去走了走", "日常→应中"),
]


async def live():
    from app.agent import companion_agent

    print("=" * 74)
    print("真实链路实测（同一老人，实际生成）")
    print("=" * 74)
    await companion_agent.prepare("e_UfToQjT5ido", "预热")  # 热链路
    for msg, note in LIVE:
        t0 = time.perf_counter()
        prepared = await companion_agent.prepare("e_UfToQjT5ido", msg)
        t_prep = time.perf_counter() - t0
        tokens = reply_max_tokens(msg, prepared["context"])
        t1 = time.perf_counter()
        text = ""
        async for piece in companion_agent.stream_reply(
                "e_UfToQjT5ido", msg, prepared["context"]):
            text += piece
        t_gen = time.perf_counter() - t1
        first = None
        # 再跑一次拿首字（上面的循环没记时间点）
        t2 = time.perf_counter()
        async for piece in companion_agent.stream_reply(
                "e_UfToQjT5ido", msg, prepared["context"]):
            first = time.perf_counter() - t2
            break
        print("  %-26s 档位%-8s 实际%-4d 字 | 前置%.2fs 生成%.2fs 首字%.2fs"
              % (note, LABEL[tokens], len(text), t_prep, t_gen, first))


async def main():
    print("=" * 74)
    print("① 分档逻辑单测")
    print("=" * 74)
    for note, msg, ctx in CASES:
        base = {"intent": "casual_chat", "emotion": "neutral",
                "emotion_intensity": 0.0, "risk_level": "low"}
        base.update(ctx)
        t = reply_max_tokens(msg, base)
        print("  %-22s %-8s <- %s" % (note, LABEL[t], msg[:30]))
    await live()


asyncio.run(main())
