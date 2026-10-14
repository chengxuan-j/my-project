"""短期记忆：最近若干轮对话 + 当前状态（主题/情绪/场景/意图），持久化在 SQLite。

替代第 1 轮的进程内 deque —— 服务重启后上下文不丢。
本轮情绪/场景先落默认值，第 4 轮 Qwen 分析后通过 update_state 回填。
"""
import logging
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from app.db import get_conn

logger = logging.getLogger(__name__)

# 短期记忆窗口（一问一答算一轮）。
# 从 20 降到 6：实测 20 轮会注入近 5000 字，预填充极慢，且模型看到大量历史
# 就倾向写长文；老人陪伴场景 6 轮足够保持连贯。
MAX_TURNS = 6

# 简单主题词表：本轮先用规则抽取"当前主题"，第 4 轮改由 Qwen 结构化输出
_TOPIC_KEYWORDS = {
    "女儿": ["女儿", "小芳", "闺女"],
    "儿子": ["儿子", "小子"],
    "孙辈": ["孙子", "孙女", "外孙"],
    "老伴": ["老伴", "老头子", "老婆子"],
    "音乐": ["歌", "音乐", "邓丽君", "听曲"],
    "老歌": ["老歌"],
    "健康": ["身体", "疼", "病", "医院", "药", "血压", "睡不"],
    "年轻时候": ["年轻", "以前", "当年", "时候的", "回忆"],
    "纺织厂": ["纺织厂", "厂里", "车间"],
    "吃饭": ["吃", "饭", "菜", "饿"],
    "天气": ["天气", "下雨", "下雪", "太阳", "冷", "热"],
    "孤独": ["孤单", "孤独", "一个人", "无聊", "没意思", "冷清"],
    "运动": ["锻炼", "散步", "太极", "早操"],
    "电视": ["电视", "电视剧", "戏曲"],
}


def extract_topic(text: str) -> Optional[str]:
    """规则抽取当前主题：命中词表次数最多的类别。"""
    counter: Counter = Counter()
    for topic, words in _TOPIC_KEYWORDS.items():
        for w in words:
            if w in text:
                counter[topic] += 1
    if not counter:
        return None
    return counter.most_common(1)[0][0]


class ShortMemory:
    """conversations 表的读写封装。"""

    def append(self, user_id: str, role: str, content: str,
               state: Optional[Dict[str, Any]] = None) -> int:
        state = state or {}
        with get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO conversations
                   (user_id, role, content, current_topic, emotion, scene, intent)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, role, content,
                 state.get("current_topic", ""),
                 state.get("emotion", "neutral"),
                 state.get("scene", "conversation"),
                 state.get("intent", "")),
            )
            return cur.lastrowid

    def recent_messages(self, user_id: str, turns: int = MAX_TURNS) -> List[Tuple[str, str]]:
        """返回最近 turns 轮 [(role, content), ...]（按时间正序）。

        如果存在摘要记录，会在开头插入一条 ('summary', summary_text) 记录。
        """
        with get_conn() as conn:
            # 先查是否有摘要
            summary_row = conn.execute(
                """SELECT content FROM conversations
                   WHERE user_id = ? AND role = 'summary'
                   ORDER BY id DESC LIMIT 1""",
                (user_id,),
            ).fetchone()

            # 查最近 turns*2 条非 summary 记录
            rows = conn.execute(
                """SELECT role, content FROM conversations
                   WHERE user_id = ? AND role != 'summary'
                   ORDER BY id DESC LIMIT ?""",
                (user_id, turns * 2),
            ).fetchall()

        result = []
        if summary_row:
            result.append(("summary", summary_row["content"]))
        result.extend([(r["role"], r["content"]) for r in reversed(rows)])
        return result

    def should_compress(self, user_id: str) -> bool:
        """检查是否需要压缩：非 summary 对话行数 > MAX_TURNS * 2 + 4。"""
        threshold = MAX_TURNS * 2 + 4  # 默认 16 条
        with get_conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM conversations
                   WHERE user_id = ? AND role != 'summary'""",
                (user_id,),
            ).fetchone()
        return row["cnt"] > threshold

    def get_old_turns(self, user_id: str, keep: int = MAX_TURNS) -> List[Tuple[str, str]]:
        """获取待压缩的旧对话（保留最近 keep 轮）。"""
        keep_rows = keep * 2
        with get_conn() as conn:
            # 先获取总行数
            total_row = conn.execute(
                """SELECT COUNT(*) as cnt FROM conversations
                   WHERE user_id = ? AND role != 'summary'""",
                (user_id,),
            ).fetchone()
            total = total_row["cnt"]

            if total <= keep_rows:
                return []

            # 获取需要压缩的旧对话
            offset = total - keep_rows
            rows = conn.execute(
                """SELECT role, content FROM conversations
                   WHERE user_id = ? AND role != 'summary'
                   ORDER BY id ASC LIMIT ? OFFSET 0""",
                (user_id, offset),
            ).fetchall()

        return [(r["role"], r["content"]) for r in rows]

    def compress_old_turns(self, user_id: str, summary: str, keep: int = MAX_TURNS) -> None:
        """压缩旧对话：删除旧行 + 插入 summary（事务内原子操作）。"""
        keep_rows = keep * 2
        with get_conn() as conn:
            # 获取总行数
            total_row = conn.execute(
                """SELECT COUNT(*) as cnt FROM conversations
                   WHERE user_id = ? AND role != 'summary'""",
                (user_id,),
            ).fetchone()
            total = total_row["cnt"]

            if total <= keep_rows:
                return

            # 计算要删除的行数
            delete_count = total - keep_rows

            # 获取要删除的最大 id
            max_id_row = conn.execute(
                """SELECT MAX(id) as max_id FROM (
                    SELECT id FROM conversations
                    WHERE user_id = ? AND role != 'summary'
                    ORDER BY id ASC LIMIT ?
                )""",
                (user_id, delete_count),
            ).fetchone()

            if max_id_row and max_id_row["max_id"]:
                max_delete_id = max_id_row["max_id"]

                # 删除旧行
                conn.execute(
                    """DELETE FROM conversations
                       WHERE user_id = ? AND role != 'summary' AND id <= ?""",
                    (user_id, max_delete_id),
                )

                # 插入 summary
                conn.execute(
                    """INSERT INTO conversations (user_id, role, content)
                       VALUES (?, 'summary', ?)""",
                    (user_id, summary),
                )

                logger.info(
                    "压缩对话：user_id=%s, 删除 %d 行, 保留 %d 行",
                    user_id, delete_count, keep_rows
                )

    def current_state(self, user_id: str) -> Dict[str, Any]:
        """当前短期状态：取最近一条带有主题的记录。"""
        with get_conn() as conn:
            row = conn.execute(
                """SELECT current_topic, emotion, scene, intent
                   FROM conversations
                   WHERE user_id = ? AND current_topic != ''
                   ORDER BY id DESC LIMIT 1""",
                (user_id,),
            ).fetchone()
        if row is None:
            return {"current_topic": "", "emotion": "neutral",
                    "scene": "conversation", "intent": ""}
        return dict(row)

    def update_state(self, user_id: str, conversation_id: int, state: Dict[str, Any]) -> None:
        """第 4 轮情绪/场景分析完成后回填指定轮次的状态。"""
        with get_conn() as conn:
            conn.execute(
                """UPDATE conversations SET
                     current_topic = COALESCE(NULLIF(?, ''), current_topic),
                     emotion = ?, scene = ?, intent = ?
                   WHERE id = ? AND user_id = ?""",
                (state.get("current_topic", ""),
                 state.get("emotion", "neutral"),
                 state.get("scene", "conversation"),
                 state.get("intent", ""),
                 conversation_id, user_id),
            )

    def record_emotion(self, user_id: str, conversation_id: int,
                       emotion: str, intensity: float) -> None:
        """情绪历史单独入 emotion_records 表（第 25 节要求），便于后续做情绪趋势。"""
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO emotion_records
                   (user_id, conversation_id, emotion, intensity)
                   VALUES (?, ?, ?, ?)""",
                (user_id, conversation_id, emotion, intensity),
            )
