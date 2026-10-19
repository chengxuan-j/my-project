# -*- coding: utf-8 -*-
"""规则 vs LLM 情境分析对照（2026-10-19）。

目的：验证规则前置层（app/emotion/rule_analyzer.py）
1. 命中率多少（命中 = 省掉一次 LLM 调用）
2. 命中时与 LLM 的结论是否一致（错判比慢更糟）
3. 各耗多少时间

结论只有"规则结论与 LLM 一致"才允许走规则；不一致的用例要补词表或调规则。
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, "E:/elderly_companion/backend")
os.chdir("E:/elderly_companion/backend")

from app.emotion.emotion_analyzer import EmotionAnalyzer  # noqa: E402
from app.emotion.rule_analyzer import rule_analyze  # noqa: E402

CASES = [
    # (句子, 备注)
    ("今天天气真好啊", "情绪+话题"),
    ("我挺好的，你别惦记", "含否定(别)→应走 LLM"),
    ("女儿打电话来了，说了半小时", "家人+family_talk"),
    ("血压有点高，明天去医院看看", "health_concern"),
    ("我想吃我妈做的饺子了", "回忆+食物"),
    ("你给我讲个故事吧", "story_request"),
    ("放首老歌听听", "music_request"),
    ("早上六点就醒了，睡不着", "morning+身体"),
    ("晚饭后去公园遛了弯", "mealtime?+outdoor"),
    ("一个人在家闷得慌", "alone+bored"),
    ("孩子们都回来了，热闹", "family_visit+happy"),
    ("我不想活了，活着没意思", "⚠️风险 high"),
    ("腰酸得厉害，站不起来", "⚠️风险/身体"),
    ("去年冬天摔过一跤，至今害怕", "长句+以前"),
    ("你还记得我上次说的那个事吗", "memory_recall"),
    ("该吃药了，几点啦", "reminder"),
    ("最近睡眠不太好，老做梦", "health_concern"),
    ("谢谢你啊，总是陪着我", "grateful"),
    ("这鬼天气，说变就变", "短+情绪弱"),
    ("今天走了三千步，累但高兴", "长+转折"),
    ("儿子说明天带孙子来看我", "family_talk"),
    ("停电了，电视看不成", "中性+场景"),
    ("夜里老是醒，醒了就睡不着", "evening+health"),
    ("想起以前在厂里的事", "nostalgic+以前"),
    ("无聊得很，没什么事干", "bored"),
]

FIELDS = ("emotion", "intent", "scene", "need", "risk_level")


async def main():
    analyzer = EmotionAnalyzer()
    hit = agree = 0
    t_rule_total = t_llm_total = 0.0
    rows = []
    for text, note in CASES:
        t = time.perf_counter()
        ruled = rule_analyze(text)
        t_rule = time.perf_counter() - t
        t_rule_total += t_rule

        t = time.perf_counter()
        llm = await analyzer.analyze(text)
        t_llm = time.perf_counter() - t
        t_llm_total += t_llm

        if ruled is None:
            rows.append((text[:22], note, "→LLM", "", ""))
            continue

        hit += 1
        mism = [f for f in FIELDS if ruled[f] != getattr(llm, f)]
        agree_flag = "一致" if not mism else "分歧:" + ",".join(mism)
        if not mism:
            agree += 1
        rows.append((text[:22], note, f"{t_rule*1000:.0f}ms", agree_flag,
                     f"LLM {t_llm:.2f}s"))

    print("=" * 78)
    for a, b, c, d, e in rows:
        print(f"  {a:<24} {b:<14} {c:<8} {d}")
    print("=" * 78)
    print(f"  规则命中      : {hit}/{len(CASES)}  ({100*hit//len(CASES)}%)")
    print(f"  命中且与LLM一致: {agree}/{hit}")
    print(f"  规则总耗时    : {t_rule_total*1000:.1f} ms（平均 {t_rule_total/max(hit,1)*1000:.2f} ms/句）")
    print(f"  LLM  总耗时    : {t_llm_total:.2f} s（平均 {t_llm_total/len(CASES):.2f} s/句）")
    print(f"  → 按此命中率，平均每句省约 {t_llm_total*(1-hit/len(CASES))/len(CASES):.2f}s" if hit else "")


asyncio.run(main())
