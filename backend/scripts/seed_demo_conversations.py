"""M-1：为演示老人（elderly_001 王阿姨）灌入生平语料，供 M0 提取质量验证与后续里程碑复用。

用法：
    cd backend
    python scripts/seed_demo_conversations.py                 # 空库直接灌
    python scripts/seed_demo_conversations.py --reset         # 先清掉该老人的旧对话再灌
    python scripts/seed_demo_conversations.py --dry-run       # 只看统计，不写库
    python scripts/seed_demo_conversations.py --reset --spread-days 45

设计要点：
- 语料与真值都在 data/demo_conversations_elderly_001.json，脚本只负责落库，便于人工修订语料。
- **幂等/安全**：目标老人已有对话时默认拒绝执行，必须显式 --reset（避免误清真实数据）。
- **回填时间**：默认把 60 轮铺到最近 30 天（可调），而不是全部落在今天——
  M4（追问时机：日报后第二天开场）与 M6（日报"本周新增 N 段"）都依赖日期分布。
- 复用 app.db.get_conn，因此遵守 COMPANION_DB_PATH，测试可指到临时库。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.db import get_conn, init_db  # noqa: E402

CORPUS_PATH = ROOT / "data" / "demo_conversations_elderly_001.json"


def _load_corpus() -> dict:
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _existing_count(user_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM conversations WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return row["cnt"]


def _purge(user_id: str) -> int:
    """清掉该老人的对话与情绪记录（--reset 专用）。返回删除的对话行数。"""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        deleted = cur.rowcount
        conn.execute("DELETE FROM emotion_records WHERE user_id = ?", (user_id,))
    return deleted


def _turn_timestamps(n: int, spread_days: int) -> list[str]:
    """把 n 轮对话均匀铺到 [now - spread_days, now) 窗口内，返回正序 created_at 列表。

    用「窗口 / 轮数」算步长，任意 spread_days 与 n 组合都不会产生非法时间值，
    且最后一轮一定早于当前时刻。
    """
    spread_days = max(1, spread_days)
    end = datetime.now().replace(second=0, microsecond=0)
    start = end - timedelta(days=spread_days)
    step = (end - start) / max(1, n)
    return [(start + step * (i + 1)).strftime("%Y-%m-%d %H:%M:%S") for i in range(n)]


def seed(user_id: str, reset: bool, dry_run: bool, spread_days: int) -> int:
    corpus = _load_corpus()
    turns = corpus["turns"]
    target_user = user_id or corpus.get("user_id", "elderly_001")

    pos = sum(1 for t in turns if t["label"]["is_life_story"])
    neg = len(turns) - pos
    holdout = [t for t in turns if t.get("split") == "holdout"]
    ho_pos = sum(1 for t in holdout if t["label"]["is_life_story"])

    print(f"语料文件：{CORPUS_PATH.name}")
    print(f"目标老人：{target_user}")
    print(f"轮次总数：{len(turns)}（生平正例 {pos} / 干扰负例 {neg}）")
    print(f"留出集 holdout：{len(holdout)} 条（正例 {ho_pos}，仅验收不调参）")
    print(f"时间铺开：最近 {spread_days} 天")

    if dry_run:
        print("\n[dry-run] 未写入数据库。")
        return 0

    init_db()  # 确保 conversations / emotion_records 表存在

    existing = _existing_count(target_user)
    if existing and not reset:
        print(
            f"\n✗ 该老人已有 {existing} 行对话。若确认要覆盖，请加 --reset。"
            "\n  （脚本不会默认清库，避免误删真实数据。）"
        )
        return 2

    if reset and existing:
        deleted = _purge(target_user)
        print(f"\n已清理旧对话 {deleted} 行（--reset）")

    stamps = _turn_timestamps(len(turns), spread_days)
    inserted = 0
    with get_conn() as conn:
        for turn, ts in zip(turns, stamps):
            topic = turn.get("topic", "")
            # user 行：无状态；assistant 行：带 topic（模拟 /chat 落库形态）
            conn.execute(
                """INSERT INTO conversations
                   (user_id, role, content, current_topic, emotion, scene, intent, created_at)
                   VALUES (?, 'user', ?, ?, 'neutral', 'conversation', '', ?)""",
                (target_user, turn["user"], topic, ts),
            )
            conn.execute(
                """INSERT INTO conversations
                   (user_id, role, content, current_topic, emotion, scene, intent, created_at)
                   VALUES (?, 'assistant', ?, ?, 'neutral', 'conversation', '', ?)""",
                (target_user, turn["assistant"], topic, ts),
            )
            inserted += 2

    final = _existing_count(target_user)
    print(f"\n✓ 写入完成：新增 {inserted} 行，当前 {target_user} 对话共 {final} 行。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="为 elderly_001 灌入生平演示语料（M-1）")
    parser.add_argument("--user-id", default="", help="目标老人 user_id，默认取语料文件中的值")
    parser.add_argument("--reset", action="store_true", help="先删除该老人已有对话再灌入")
    parser.add_argument("--dry-run", action="store_true", help="只打印统计，不写库")
    parser.add_argument("--spread-days", type=int, default=30, help="把语料铺开到最近多少天（默认 30）")
    args = parser.parse_args()
    return seed(args.user_id, args.reset, args.dry_run, args.spread_days)


if __name__ == "__main__":
    raise SystemExit(main())
