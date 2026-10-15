"""M0：生平故事提取质量探针。

读演示语料（或数据库里的真实对话）→ 逐轮跑提取 prompt → 输出 JSON 报告供
scripts/eval_story_extraction.py 计算 precision/recall。

用法：
    cd backend
    python scripts/extract_stories_probe.py                    # 跑演示语料（全部 60 轮）
    python scripts/extract_stories_probe.py --split holdout     # 只跑留出集
    python scripts/extract_stories_probe.py --source db --user-id elderly_001
    python scripts/extract_stories_probe.py --out data/story_probe_report.json

无 QWEN_API_KEY 时不会报错：报告里标 no_key=true，退出码 0（保证无 Key 也能跑通 CI）。
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.db import get_conn, init_db  # noqa: E402
from app.memoir.prompts import EXTRACT_SYSTEM_PROMPT  # noqa: E402
from app.memoir.story_extractor import StoryExtractor  # noqa: E402

CORPUS_PATH = ROOT / "data" / "demo_conversations_elderly_001.json"
DEFAULT_OUT = ROOT / "data" / "story_probe_report.json"


def _load_corpus_items(split: str, limit: int | None) -> list[dict]:
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        corpus = json.load(f)
    items = []
    for turn in corpus["turns"]:
        if split != "all" and turn.get("split") != split:
            continue
        items.append({
            "id": turn["id"],
            "split": turn.get("split", "train"),
            "user": turn["user"],
            "assistant": turn.get("assistant", ""),
            "label_is_story": bool(turn["label"]["is_life_story"]),
            "label_era_tags": turn["label"].get("era_tags", []),
        })
    return items[:limit] if limit else items


def _load_db_items(user_id: str, split: str, limit: int | None) -> list[dict]:
    """从数据库配对 (user, assistant) 对话。split 在此模式下无意义（全部标 db）。"""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, role, content FROM conversations
               WHERE user_id = ? AND role IN ('user', 'assistant')
               ORDER BY id ASC""",
            (user_id,),
        ).fetchall()
    items, pending_user = [], None
    for row in rows:
        if row["role"] == "user":
            pending_user = row["content"]
        elif pending_user is not None:
            items.append({
                "id": row["id"],
                "split": "db",
                "user": pending_user,
                "assistant": row["content"],
                "label_is_story": None,  # 真实对话无标注
                "label_era_tags": [],
            })
            pending_user = None
    return items[:limit] if limit else items


async def _run(items: list[dict]) -> dict:
    extractor = StoryExtractor()
    no_key = not extractor.is_configured
    results = []
    extracted = 0

    if no_key:
        # 无 Key 时直接短路，避免逐轮报同样的错（CI / 本地无 Key 也能产出完整报告骨架）
        print("  ⚠ 未配置 QWEN_API_KEY，跳过全部 LLM 调用（报告标 no_key=true）")
        for item in items:
            results.append({
                "id": item["id"], "split": item["split"], "user": item["user"],
                "label_is_story": item["label_is_story"],
                "predicted_is_story": False, "prediction": None, "error": "no_key",
            })
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "model": getattr(extractor.client, "model", ""),
            "prompt_sha256": hashlib.sha256(EXTRACT_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12],
            "no_key": True, "total": len(items), "extracted": 0, "items": results,
        }

    for i, item in enumerate(items, 1):
        pred, raw, error = await extractor.extract_debug(item["user"], item["assistant"])
        if pred:
            extracted += 1
        row = {
            "id": item["id"],
            "split": item["split"],
            "user": item["user"],
            "label_is_story": item["label_is_story"],
            "predicted_is_story": bool(pred),
            "prediction": pred,
            "error": error,
        }
        if error:  # 仅失败时保留原文，便于复盘 prompt
            row["raw"] = raw[:400]
        results.append(row)
        flag = "命中" if pred else ("跳过" if error is None else f"失败({error})")
        print(f"  [{i}/{len(items)}] #{item['id']} {flag}")

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": getattr(extractor.client, "model", ""),
        "prompt_sha256": hashlib.sha256(EXTRACT_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12],
        "no_key": no_key,
        "total": len(items),
        "extracted": extracted,
        "items": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生平故事提取质量探针（M0）")
    parser.add_argument("--source", choices=["corpus", "db"], default="corpus",
                        help="corpus=读演示语料（带标注）；db=读数据库真实对话（无标注）")
    parser.add_argument("--user-id", default="elderly_001", help="--source db 时的老人 user_id")
    parser.add_argument("--split", choices=["all", "train", "holdout"], default="all",
                        help="--source corpus 时可只跑某一划分")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 轮（调试用）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="报告输出路径")
    args = parser.parse_args()

    if args.source == "corpus":
        items = _load_corpus_items(args.split, args.limit)
        source_desc = f"corpus:{CORPUS_PATH.name} split={args.split}"
    else:
        items = _load_db_items(args.user_id, args.split, args.limit)
        source_desc = f"db:{args.user_id}"

    if not items:
        print(f"✗ 没有可处理的对话（{source_desc}）。若是 db 模式，请先跑 seed_demo_conversations.py。")
        return 1

    print(f"数据来源：{source_desc}")
    print(f"待处理：{len(items)} 轮\n")

    report = asyncio.run(_run(items))
    report["source"] = source_desc

    out_path = Path(args.out)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n模型：{report['model']}｜prompt 版本：{report['prompt_sha256']}")
    if report["no_key"]:
        print("⚠ 未配置 QWEN_API_KEY：本轮未真正调用 LLM，报告已标记 no_key=true。")
    else:
        print(f"判定为生平故事：{report['extracted']} / {report['total']} 轮")
    print(f"报告已写入：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
