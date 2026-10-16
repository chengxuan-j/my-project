# -*- coding: utf-8 -*-
"""表情关怀话术闭环探针（2026-10-16，机器狗调试前软件自测）。

验证三条：
1. 播报策略：happy/sad/angry/fear/disgust 播，neutral/surprise 不播；
2. 轮换：同一用户同一表情连续触发，话术不重复（轮完一圈才回头）；
3. 真实链路降级：execute_actions + push_to_dog 在狗不在线时不抛异常、
   返回 False（指令已构造，静默失败，不影响主流程）。
"""
import asyncio
import os
import sys

sys.path.insert(0, "E:/elderly_companion/backend")
os.chdir("E:/elderly_companion/backend")

from app.services import care_speech  # noqa: E402


def test_policy():
    print("== 1. 播报策略 ==")
    for e in ["happy", "sad", "angry", "fear", "disgust", "neutral", "surprise"]:
        print(f"  {e:9s} -> {'播报' if care_speech.should_speak(e) else '不播（%s）' % care_speech.MUTE_REASONS.get(e, '?')}")


def test_rotation():
    print("== 2. 轮换（王阿姨连续 5 次开心）==")
    seen = []
    for _ in range(5):
        t, src = care_speech.pick_canned("happy", "elderly_001"), "canned"
        seen.append(t)
    for i, t in enumerate(seen, 1):
        print(f"  第{i}次: {t}")
    uniq = len(set(seen[:3]))
    print(f"  前三句去重数: {uniq}（应为 3，说明在轮换）")


async def test_pick_speech_async():
    print("== 3. pick_speech（默认写死模式）==")
    t, src = await care_speech.pick_speech("sad", "elderly_001", "难过")
    print(f"  sad -> [{src}] {t}")
    t, src = await care_speech.pick_speech("neutral", "elderly_001", "平静")
    print(f"  neutral -> [{src}] {t!r}（应为空）")


async def test_full_chain_degradation():
    print("== 4. 真实链路降级（狗不在线也应静默）==")
    from app.services.dog_control import execute_actions, push_to_dog
    from app.config import get_settings

    settings = get_settings()
    t, src = await care_speech.pick_speech("happy", "probe_user", "开心")
    reached = await execute_actions(settings.dog_base_url, [("前跳", None)], timeout=settings.dog_timeout)
    spoke = await push_to_dog(t)
    print(f"  话术: {t}")
    print(f"  动作 reached={reached}（False=狗不在线，预期）")
    print(f"  发声 spoke={spoke}（False=无设备/未连，预期）")
    print("  未抛异常 = 降级路径 OK")


async def main():
    test_policy()
    test_rotation()
    await test_pick_speech_async()
    await test_full_chain_degradation()


asyncio.run(main())
