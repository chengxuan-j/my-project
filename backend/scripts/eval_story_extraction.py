"""M0：提取质量评估。

读 extract_stories_probe.py 产出的报告 → 对标注集算 precision / recall / F1
（整体 + train/holdout 分开），并列出误判明细供 prompt 调参。

用法：
    cd backend
    python scripts/eval_story_extraction.py
    python scripts/eval_story_extraction.py --report data/story_probe_report.json --min-precision 0.8

验收线（开发计划 M0）：precision ≥ 0.80 —— 宁可漏，不可误。
无 Key（no_key=true）时跳过评分并退出 0，不判失败。
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

DEFAULT_REPORT = ROOT / "data" / "story_probe_report.json"


def _metrics(rows: list[dict]) -> dict:
    tp = sum(1 for r in rows if r["label_is_story"] and r["predicted_is_story"])
    fp = sum(1 for r in rows if not r["label_is_story"] and r["predicted_is_story"])
    fn = sum(1 for r in rows if r["label_is_story"] and not r["predicted_is_story"])
    tn = sum(1 for r in rows if not r["label_is_story"] and not r["predicted_is_story"])
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": f1, "n": len(rows)}


def _print_metrics(title: str, m: dict) -> None:
    print(f"\n【{title}】样本 {m['n']}｜TP {m['tp']} / FP {m['fp']} / FN {m['fn']} / TN {m['tn']}")
    print(f"  precision = {m['precision']:.3f}   recall = {m['recall']:.3f}   F1 = {m['f1']:.3f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="生平故事提取质量评估（M0）")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="探针报告路径")
    parser.add_argument("--min-precision", type=float, default=0.80, help="precision 验收线（默认 0.80）")
    args = parser.parse_args()

    path = Path(args.report)
    if not path.exists():
        print(f"✗ 找不到报告 {path}，请先运行 extract_stories_probe.py")
        return 1

    report = json.loads(path.read_text(encoding="utf-8"))
    print(f"报告：{path.name}｜生成于 {report.get('generated_at')}｜prompt 版本 {report.get('prompt_sha256')}")

    if report.get("no_key"):
        print("\n⚠ 报告标记 no_key=true（未真正调用 LLM），无法评分。")
        print("  请先在 backend/.env 配置 QWEN_API_KEY，再重跑：")
        print("    python scripts/extract_stories_probe.py && python scripts/eval_story_extraction.py")
        return 0

    labeled = [r for r in report.get("items", []) if r.get("label_is_story") is not None]
    if not labeled:
        print("\n✗ 报告中没有带标注的样本（可能用了 --source db），无法评分。")
        return 1

    overall = _metrics(labeled)
    _print_metrics("总体", overall)
    for split in ("train", "holdout"):
        rows = [r for r in labeled if r.get("split") == split]
        if rows:
            _print_metrics(f"{split}（{'调参集' if split == 'train' else '留出集·仅验收'}）", _metrics(rows))

    fps = [r for r in labeled if not r["label_is_story"] and r["predicted_is_story"]]
    fns = [r for r in labeled if r["label_is_story"] and not r["predicted_is_story"]]
    if fps:
        print(f"\n误报 FP（闲聊被判成往事，代价最大，优先修）共 {len(fps)} 条：")
        for r in fps:
            title = (r.get("prediction") or {}).get("title", "")
            print(f"  - #{r['id']} “{r['user'][:26]}…” → {title}")
    if fns:
        print(f"\n漏报 FN（往事被漏掉）共 {len(fns)} 条：")
        for r in fns:
            print(f"  - #{r['id']} “{r['user'][:26]}…”")

    ok = overall["precision"] >= args.min_precision
    print(f"\n验收：precision {overall['precision']:.3f} {'≥' if ok else '<'} {args.min_precision:.2f} "
          f"→ {'通过 ✅' if ok else '未达标 ❌（继续调 prompt）'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
