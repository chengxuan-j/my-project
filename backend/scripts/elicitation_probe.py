"""M4：缺口追问的小样本回放（离线，不依赖 LLM Key）。

M4 的验收是「小样本回放（M-1 语料 + 手工构造回避/高风险场景），
人工评估"像关心 vs 像调查"」。本脚本把语料按真实顺序回放一遍，
**逐轮**跑一次追问决策，把每一次"问 / 不问"及其理由打出来。

它要回答的核心问题不是我能不能问，而是**我克制到什么程度**：
一个陪伴产品里，追问频率本身就是产品态度。所以报告末尾会给出
「回放 N 轮，实际开口 M 次」，以及每一次的触发信号。

风险等级与情绪强度没有模型可调（无 Key），这里按**可复现的规则**模拟：
- 语料里情绪基调为「创伤」的轮次 → risk_level 视为 medium（不该追问）；
- 其余为 low。
这个模拟只影响本次回放的输入，不进入任何生产路径。

**回放推进模拟时钟**：每 20 轮 +12 小时（当作"聊完这一阵、隔天再来"），
并据此算出「今天是否第一次开口」。这样才看得出跨天的真实节奏——
如果时钟不动，60 轮会被压成一段连续对话，「每会话 1 问」的硬上限会把
后面 57 轮全部拦下，报告就只剩"上限生效了"这一个信息。

**一处已知的模拟失真**：语料里每轮的 `topic` 与该轮故事的 `title` 同源，
所以"聊到相关话题顺带问"这个信号在回放里**恒为真**。真实对话中它时真时假，
因此这里报出的开口次数应视为**下界**而不是典型值——真正压住频率的是
会话上限与 cooldown。

用法：
    cd backend
    python scripts/elicitation_probe.py
    python scripts/elicitation_probe.py --verbose    # 连"被拦下"的轮次也逐条打印

**不改真实库**：默认在系统临时目录建一次性 SQLite，跑完即删。
"""
import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _probe_common import (  # noqa: E402
    CORPUS_PATH,
    cleanup,
    label_to_extraction,
    load_corpus,
    seed_corpus_stories,
    use_temp_db,
)

_TMP_DB = use_temp_db("elicitation_probe")

from app.db.base import get_session_factory  # noqa: E402
from app.db.models import Conversation  # noqa: E402
from app.memoir import elicitation as E  # noqa: E402
from app.memoir.gap_detector import detect_gaps  # noqa: E402
from app.repositories.story_repo import ElicitationRepo, StoryRepo  # noqa: E402

# 近期发言长度的滑动窗口（用于"回复变短"判定）
LEN_WINDOW = 4


def _risk_for(turn: dict) -> str:
    """可复现的风险模拟：创伤基调 → medium；其余 low。"""
    tone = (turn.get("label") or {}).get("emotion_tone") or "平淡"
    return "medium" if tone == "创伤" else "low"


def _intensity_for(turn: dict) -> float:
    tone = (turn.get("label") or {}).get("emotion_tone") or "平淡"
    return {"创伤": 0.7, "辛酸": 0.45, "自豪": 0.4, "温暖": 0.35}.get(tone, 0.2)


async def seed_gaps(corpus: dict, user_id: str) -> int:
    """按语料标签里的 missing 排出缺口队列（与 M1 的入队口径一致）。"""
    async with get_session_factory()() as session:
        stories = await StoryRepo(session).list_archived(user_id)
        # 语料正例与故事一一对应（同序灌入）
        positives = [
            t for t in corpus.get("turns", [])
            if (t.get("label") or {}).get("is_life_story")
        ]
        queue = ElicitationRepo(session)
        total = 0
        for story, turn in zip(stories, positives):
            for gap in detect_gaps(label_to_extraction(turn)):
                await queue.add(
                    user_id, story.id,
                    question=gap["question"], gap_type=gap["gap_type"],
                    priority=gap["priority"],
                )
                total += 1
        await session.commit()
    return total


async def replay(corpus: dict, user_id: str, verbose: bool) -> dict:
    """回放语料，逐轮跑一次追问决策。

    时序严格照生产：**决策发生在当前轮落库之前**（真实链路是
    `build_context` 先跑、`save_turn` 后跑），所以本轮的消息在决策时
    还查不到——"今天是否第一次开口"正是靠"上一条老人消息是不是今天"推出来的。
    探针必须按同样顺序写库，否则每轮都会被判成"今天第一次开口"。

    节奏：一轮 3 分钟（同一段连续对话）；每 20 轮 +14 小时（隔天再来）。

    追问上限与 cooldown **从配置读**（`MEMOIR_MAX_ASKS_PER_SESSION` /
    `MEMOIR_GAP_COOLDOWN_DAYS`），不是写死——否则这个探针就只是在测"常数等于常数"，
    拿它给产品取值做依据等于自欺。想对比不同取值：
    `MEMOIR_MAX_ASKS_PER_SESSION=2 python scripts/elicitation_probe.py`
    """
    from app.config import get_settings

    settings = get_settings()
    max_asks = max(1, int(settings.memoir_max_asks_per_session))
    cooldown_days = max(1, int(settings.memoir_gap_cooldown_days))

    turns = corpus.get("turns", [])
    lines: list[str] = []
    asked: list[dict] = []
    blocked: list[dict] = []
    recent_lens: list[int] = []
    # 起点往前推，让 cooldown 与跨天会话都能被真正走到
    clock = datetime.now() - timedelta(days=max(3, cooldown_days))

    for i, turn in enumerate(turns):
        text = turn.get("user") or ""

        async with get_session_factory()() as session:
            signals = await E.build_signals(
                session, user_id,
                risk_level=_risk_for(turn),
                current_len=len(text),
                recent_user_len_avg=(
                    sum(recent_lens) / len(recent_lens) if recent_lens else 0.0
                ),
                emotion_intensity=_intensity_for(turn),
                topic=turn.get("topic") or "",
                max_asks_per_session=max_asks,
                now=clock,
            )
            candidate = await E.pick_candidate(session, user_id, now=clock)
            decision = E.should_elicit(candidate, signals)

            if decision is not None:
                await E.commit_ask(session, decision, now=clock, cooldown_days=cooldown_days)
                asked.append({"turn": i + 1, "day": clock.date().isoformat(),
                              "topic": turn.get("topic"),
                              "ask": decision.hint, "why": decision.reason})
                lines.append(
                    f"{clock:%m-%d %H:%M} 轮 {i + 1:>3} 💬 问：{decision.hint}"
                    f"   ← {decision.reason}"
                )
            else:
                reason = E.gate_blocked(signals, candidate) or "无正向信号"
                blocked.append({"turn": i + 1, "reason": reason})
                if verbose:
                    lines.append(f"{clock:%m-%d %H:%M} 轮 {i + 1:>3} ·  不问（{reason}）")

            # 决策之后才落库——顺序反了会让"今天第一次开口"永远为真
            session.add(Conversation(
                user_id=user_id, role="user", content=text,
                current_topic=turn.get("topic") or "", created_at=clock,
            ))
            await session.commit()

        recent_lens.append(len(text))
        recent_lens = recent_lens[-LEN_WINDOW:]
        clock += timedelta(hours=14) if (i + 1) % 20 == 0 else timedelta(minutes=3)

    return {
        "lines": lines, "asked": asked, "blocked": blocked, "turns": len(turns),
        "max_asks": max_asks, "cooldown_days": cooldown_days,
    }


async def scenario_checks(corpus: dict, user_id: str) -> list[tuple[str, bool, str]]:
    """手工构造的场景：三个门禁 + 无理由不问 + 回避，逐个验证。"""
    results: list[tuple[str, bool, str]] = []
    # 回放结束时模拟时钟已跑到未来，cooldown 也留在未来；这里再往后拨 30 天，
    # 保证"有候选"这个前提成立——否则门禁 3 会把后面几条检查一起短路掉。
    future = datetime.now() + timedelta(days=30)

    async with get_session_factory()() as session:
        cand = await E.pick_candidate(session, user_id, now=future)
        results.append(("存在可追问的候选（后续检查的前提）", cand is not None,
                        f"candidate={'有' if cand else '无'}"))

        # 门禁1：高风险
        d = E.should_elicit(cand, E.TurnSignals(
            risk_level="high", is_first_turn_of_day=True,
            current_len=10, recent_user_len_avg=40.0,
        ))
        results.append(("高风险时绝对不追问", d is None, f"risk=high → {d}"))

        # 门禁2：会话上限
        d = E.should_elicit(cand, E.TurnSignals(
            risk_level="low", is_first_turn_of_day=True, session_asks=1,
            max_asks_per_session=1, current_len=10, recent_user_len_avg=40.0,
        ))
        results.append(("本会话问满就不再问", d is None, f"asks=1/1 → {d}"))

        # 门禁3：没有过 cooldown 的候选
        d = E.should_elicit(None, E.TurnSignals(
            risk_level="low", is_first_turn_of_day=True,
            current_len=10, recent_user_len_avg=40.0,
        ))
        results.append(("没有候选就不问", d is None, f"candidate=None → {d}"))

        # 正向信号：门禁全过但没理由，也不问
        d = E.should_elicit(cand, E.TurnSignals(
            risk_level="low", is_first_turn_of_day=False, topic="今天天气不错",
            current_len=40, recent_user_len_avg=40.0, emotion_intensity=0.2,
        ))
        results.append(("门禁全过但没触发信号，仍然不问", d is None, f"→ {d}"))

    # 回避处理：永久尊重
    async with get_session_factory()() as session:
        story = (await StoryRepo(session).list_archived(user_id))[0]
        await StoryRepo(session).mark_avoid(story.id)
        await session.commit()
        after = await StoryRepo(session).get(story.id)
        locked = (
            after.visibility == "private" and after.visibility_locked
            and await StoryRepo(session).set_visibility(story.id, "family") == "locked"
        )
        results.append(
            ("回避后永久 private 且锁定，改不回来", locked,
             f"visibility={after.visibility} locked={after.visibility_locked}")
        )

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true", help="连被拦下的轮次也逐条打印")
    args = parser.parse_args()

    corpus = load_corpus()

    async def run():
        user_id, stories = await seed_corpus_stories(corpus)
        gaps = await seed_gaps(corpus, user_id)
        report = await replay(corpus, user_id, args.verbose)
        checks = await scenario_checks(corpus, user_id)
        return user_id, stories, gaps, report, checks

    try:
        user_id, stories, gaps, report, checks = asyncio.run(run())

        print(f"语料：{CORPUS_PATH.name}｜故事 {stories} 条｜缺口队列 {gaps} 条")
        print(f"回放 {report['turns']} 轮对话"
              f"｜会话上限 {report['max_asks']} 问｜cooldown {report['cooldown_days']} 天"
              f"（如需对比：加 MEMOIR_MAX_ASKS_PER_SESSION / MEMOIR_GAP_COOLDOWN_DAYS 环境变量）")
        print("-" * 66)
        if report["lines"]:
            print("\n".join(report["lines"]))
        else:
            print("（没有任何一轮触发追问）")
        print("-" * 66)

        n_asked = len(report["asked"])
        print(f"实际开口：{n_asked} 次 / {report['turns']} 轮"
              f"（{n_asked / max(1, report['turns']) * 100:.1f}%）")
        reasons: dict[str, int] = {}
        for item in report["blocked"]:
            reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
        for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"  拦下 {count:>3} 次：{reason}")

        print("-" * 66)
        print("手工场景检查：")
        all_ok = True
        for name, passed, detail in checks:
            all_ok = all_ok and passed
            print(f"  {'✅' if passed else '❌'} {name}（{detail}）")

        # 克制性验收：回放里不该出现"每几轮就问一次"
        restrained = n_asked <= max(1, report["turns"] // 10)
        print("-" * 66)
        print(f"克制性（开口次数 ≤ 轮数/10）：{'通过' if restrained else '不通过'}"
              f"（{n_asked} ≤ {max(1, report['turns'] // 10)}）")
        verdict = all_ok and restrained
        print(f"验收：{'通过' if verdict else '不通过'}")
    finally:
        cleanup(_TMP_DB)
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
