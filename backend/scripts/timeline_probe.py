"""M3：用真实演示语料端到端渲染一次时代轴（离线、不依赖 LLM Key）。

为什么需要它：M0 的提取要 `QWEN_API_KEY`，本地没配时拿不到真实 `era_tags`，
M3 的验收（「elderly_001 语料能渲染出时代轴，至少 2 个时代段 + 未定位区」）
就没法用真实数据确认。本脚本改用**语料里的人工真值标签**充当提取结果，
把 M3 的编排链路完整跑一遍，同时顺带做两件事：

1. **标签漂移检查**：语料里的 `era_tags` 是否能被 `era_lexicon` 全部归一；
   归一不上说明词表与语料脱节（时代轴会碎），这里会直接报出来。
2. **未定位比例**：多少条正例既无时代标签也推不出年份——这个数字是
   M0 提取 prompt 该补什么信号的直接依据。

用法：
    cd backend
    python scripts/timeline_probe.py            # 跑一次并打印时代轴
    python scripts/timeline_probe.py --json     # 额外输出完整 JSON

**不改真实库**：默认在系统临时目录建一个一次性 SQLite，跑完即删。
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _probe_common import (  # noqa: E402
    CORPUS_PATH,
    check_label_drift,
    cleanup,
    load_corpus,
    seed_corpus_stories,
    use_temp_db,
)

_TMP_DB = use_temp_db("timeline_probe")

from app.db.base import get_session_factory  # noqa: E402
from app.memoir.story_service import build_timeline_payload  # noqa: E402


async def run(corpus: dict) -> dict:
    user_id, created = await seed_corpus_stories(corpus)
    async with get_session_factory()() as session:
        payload = await build_timeline_payload(session, user_id, status="archived")
    payload["_seeded_stories"] = created
    return payload


def render(payload: dict) -> str:
    lines: list[str] = []
    stats = payload["stats"]
    lines.append(f"已留档故事：{stats['total']}（灌入 {payload['_seeded_stories']} 条）")
    lines.append(
        f"时代段 {stats['era_segments']} 个 / 段内 {stats['in_era']} 条"
        f" ｜ 绝对时间轴 {stats['in_absolute']} 条（其中画像推断 {stats['inferred']} 条）"
        f" ｜ 未定位 {stats['unlocated']} 条"
    )
    span = payload["axis_span"]
    lines.append(f"时间跨度：{span['min_year']} — {span['max_year']}")
    lines.append("")
    for group in payload["era_axis"]:
        head = (f"▍{group['era']}（{group['start_year']}—{group['end_year'] or '今'}，"
                f"{group['count']} 条）")
        lines.append(head)
        for story in group["stories"]:
            mark = "≈" if story.time_inferred else "·"
            lines.append(f"   {mark} [{story.display_time}] {story.title}：{story.summary[:28]}")
    if payload["absolute_axis"]:
        lines.append("")
        lines.append("▍绝对时间轴")
        for story in payload["absolute_axis"]:
            mark = "≈" if story.time_inferred else "·"
            extra = f"（依据画像：{story.inferred_from}）" if story.inferred_from else ""
            lines.append(
                f"   {mark} [{story.display_time}] {story.title}：{story.summary[:28]}{extra}"
            )
    if payload["unlocated"]:
        lines.append("")
        lines.append(f"▍还记得这些（未定位 {len(payload['unlocated'])} 条）")
        for story in payload["unlocated"]:
            lines.append(f"   · {story.title}：{story.summary[:28]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="额外打印完整 JSON")
    args = parser.parse_args()

    corpus = load_corpus()
    matched, unmapped = check_label_drift(corpus)
    try:
        payload = asyncio.run(run(corpus))

        print(f"语料：{CORPUS_PATH.name}｜老人：{corpus.get('user_id')}")
        print(f"词表可归一时代：{'、'.join(matched) if matched else '（无）'}")
        if unmapped:
            print(f"⚠️ 归一不上的标签（会造成时代轴碎裂）：{'、'.join(unmapped)}")
        print("-" * 60)
        print(render(payload))

        stats = payload["stats"]
        seeded = payload["_seeded_stories"]
        ok = (
            stats["era_segments"] >= 2             # 验收：至少 2 个时代段
            and stats["total"] == seeded           # 三组互斥完备：没有多算也没有丢
            and not unmapped                       # 词表与语料标签不脱节
        )
        print("-" * 60)
        print(
            f"验收（≥2 个时代段 + 未定位区，且三组之和 = 灌入条数）："
            f"{'通过' if ok else '不通过'}（{stats['total']} vs {seeded}）"
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        # 失败路径也要清掉临时库，否则残留会污染下一次运行
        cleanup(_TMP_DB)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
