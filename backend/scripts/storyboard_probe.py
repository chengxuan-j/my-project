"""M5：用真实演示语料端到端出一份故事板（离线，不依赖 LLM Key）。

M5 的验收是「`elderly_001` 出一个带完整提示词包、可 TTS 播放的故事板」。
本脚本用与 `timeline_probe.py` 相同的离线替身（语料人工标签充当提取结果），
把 M5 的编排链路真跑一遍，并逐条检查契约 4 / 6 的硬约束：

- 旁白是否第一人称、是否优先用了老人原话；
- 画面提示里有没有漏出人脸类描述；
- 免责声明是否强制存在；
- 状态是否止于 `prompt_ready`、有没有任何渲染痕迹。

用法：
    cd backend
    python scripts/storyboard_probe.py            # 跑一次并打印故事板
    python scripts/storyboard_probe.py --seconds 45 --json

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
    cleanup,
    load_corpus,
    seed_corpus_stories,
    use_temp_db,
)

_TMP_DB = use_temp_db("storyboard_probe")

from app.db.base import get_session_factory  # noqa: E402
from app.memoir import storyboard as SB  # noqa: E402
from app.memoir.story_service import create_compilation  # noqa: E402
from app.memoir.presenter import compilation_to_dict  # noqa: E402


async def run(corpus: dict, total_seconds: int) -> tuple[dict, int]:
    user_id, created = await seed_corpus_stories(corpus)
    async with get_session_factory()() as session:
        comp, reason = await create_compilation(
            session, user_id, total_seconds=total_seconds, created_by=user_id
        )
        await session.commit()
        if comp is None:
            raise SystemExit(f"编排失败：{reason}")
        return compilation_to_dict(comp).model_dump(), created


def audit(package: dict, comp: dict) -> tuple[list[str], list[str]]:
    """逐条检查契约硬约束，返回 (通过项, 问题项)。"""
    ok: list[str] = []
    bad: list[str] = []
    scenes = package.get("scenes") or []

    if not scenes:
        bad.append("故事板是空的")
        return ok, bad

    # 契约4：旁白不得把老人写成第三人称。
    # 判据不看"有没有『我』"——中文主语省略是常态；只看模型有没有**引入**
    # 老人原话里没有的第三人称指代。
    drifted = [
        s["index"] for s in scenes
        if SB.introduces_third_person(s.get("narration") or "", s.get("source_evidence") or "")
    ]
    (ok if not drifted else bad).append(
        "旁白没有把老人写成第三人称" if not drifted
        else f"这些段落的旁白把老人写成了第三人称：{drifted}"
    )

    # 契约4：旁白要么是原话，要么与原话足够接近（不能被改得面目全非）
    far = [
        s["index"] for s in scenes
        if s.get("narration_source") == "model"
        and SB.similarity(s.get("narration") or "",
                          s.get("source_evidence") or "") < SB.NARRATION_MIN_SIMILARITY
    ]
    (ok if not far else bad).append(
        "改写过的旁白都与原话足够接近" if not far
        else f"这些段落改写幅度过大：{far}"
    )

    originals = [s["index"] for s in scenes if s.get("narration_source") == "original"]
    ok.append(f"直接用老人原话的段落：{len(originals)}/{len(scenes)}")

    # 契约6 延伸：画面提示不得出现人脸类词
    facey = [s["index"] for s in scenes
             if any(w in (s.get("visual_prompt") or "").lower() for w in SB.FACE_BAN_WORDS)]
    (ok if not facey else bad).append(
        "画面提示无人脸描述" if not facey else f"这些段落漏出人脸描述：{facey}"
    )

    # 免责声明强制存在
    (ok if package.get("disclaimer") else bad).append(
        "免责声明存在" if package.get("disclaimer") else "缺少免责声明"
    )

    # 出处必须与老人原话一致
    mismatched = [s["index"] for s in scenes if not s.get("source_evidence")]
    (ok if not mismatched else bad).append(
        "每段都有出处" if not mismatched else f"这些段落缺出处：{mismatched}"
    )

    # 时长由代码分配，且不超过请求值
    total = package.get("total_seconds") or 0
    requested = package.get("requested_seconds") or 0
    (ok if 0 < total <= requested else bad).append(
        f"时长可控：{total}s / 请求 {requested}s"
        if 0 < total <= requested else f"时长异常：{total}s / 请求 {requested}s"
    )

    # 契约6：状态止于 prompt_ready，没有任何渲染产物
    contract6 = (
        comp.get("status") == "prompt_ready"
        and comp.get("video_url") is None
        and comp.get("rendered") is False
        and package.get("render_engine") is None
    )
    (ok if contract6 else bad).append(
        "契约6：止于 prompt_ready，无视频产物" if contract6
        else f"契约6 违约：status={comp.get('status')} video_url={comp.get('video_url')} "
             f"rendered={comp.get('rendered')}"
    )

    return ok, bad


def render(comp: dict, package: dict) -> str:
    lines: list[str] = []
    lines.append(
        f"《{comp['title']}》｜状态 {comp['status']}｜{len(package['scenes'])} 段"
        f"｜约 {package['total_seconds']} 秒｜LLM {'可用' if package['llm_used'] else '不可用（线性降级）'}"
    )
    lines.append(f"片长约：{package['total_seconds']}s（请求 {package['requested_seconds']}s）")
    lines.append(f"视角：{package['perspective']}｜渲染引擎：{package['render_engine']}")
    lines.append("")
    for s in package["scenes"]:
        tag = "原话" if s["narration_source"] == "original" else "改写"
        lines.append(
            f"▍第 {s['index']} 段｜{s['display_time'] or s['era'] or '时间不详'}"
            f"｜{s['duration_seconds']}s｜{s['title']}｜旁白：{tag}"
        )
        lines.append(f"   旁白：{s['narration']}")
        lines.append(f"   画面：{s['visual_prompt']}")
    lines.append("")
    lines.append(f"（免责声明）{package['disclaimer']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=60, help="故事板目标总时长")
    parser.add_argument("--json", action="store_true", help="额外打印完整 JSON")
    args = parser.parse_args()

    corpus = load_corpus()
    try:
        comp, created = asyncio.run(run(corpus, args.seconds))
        package = comp["prompt_package"]

        print(f"语料：{CORPUS_PATH.name}｜老人：{corpus.get('user_id')}｜可用故事 {created} 条")
        print("-" * 66)
        print(render(comp, package))

        ok, bad = audit(package, comp)
        print("-" * 66)
        for item in ok:
            print(f"  ✅ {item}")
        for item in bad:
            print(f"  ❌ {item}")
        verdict = not bad
        print(f"验收（带完整提示词包 + 契约4/6 硬约束）：{'通过' if verdict else '不通过'}")

        if args.json:
            print(json.dumps(comp, ensure_ascii=False, indent=2))
    finally:
        # 失败路径也要清掉临时库，否则残留会污染下一次运行
        cleanup(_TMP_DB)
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
