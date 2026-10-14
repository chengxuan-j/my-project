"""音乐推荐：data/music.json + 规则打分。

设计文档第十九节：根据 老人喜好 + 当前情绪 + 当前场景 选择推荐内容。
第一阶段不接在线音乐平台，只返回歌名/歌手/标签。
"""
import json
import logging
import os
import random
from typing import Any, Dict, List

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

MUSIC_PATH = os.path.join(BASE_DIR, "data", "music.json")

# 情绪 → 偏好标签
_EMOTION_TAGS = {
    "lonely": ["陪伴", "深情", "舒缓"],
    "sad": ["舒缓", "深情", "怀旧"],
    "bored": ["轻松", "欢快", "愉快"],
    "happy": ["欢快", "轻松", "积极"],
    "anxious": ["舒缓", "经典", "积极"],
    "worried": ["舒缓", "积极", "鼓励"],
    "angry": ["舒缓", "经典"],
    "tired": ["舒缓", "轻松"],
    "nostalgic": ["怀旧", "经典", "民歌"],
    "grateful": ["深情", "经典"],
    "neutral": ["经典", "舒缓"],
}

# 场景 → 偏好标签
_SCENE_TAGS = {
    "alone": ["陪伴", "舒缓", "怀旧"],
    "mealtime": ["轻松", "欢快"],
    "morning": ["轻松", "积极"],
    "evening": ["舒缓", "深情"],
    "rest": ["舒缓"],
}


def _load() -> List[Dict[str, Any]]:
    try:
        with open(MUSIC_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("读取 music.json 失败: %s", e)
        return []


def recommend(
    profile,
    emotion: str,
    scene: str,
    limit: int = 3,
    liked_titles: set = None,
    disliked_titles: set = None,
) -> List[Dict[str, Any]]:
    """返回推荐列表（含每首的推荐理由，按得分降序）。"""
    songs = _load()
    if not songs:
        return []

    # 老人的歌手/歌曲偏好（画像里是歌手名，如"邓丽君"）
    fav_artists = {a for a in profile.favorite_music}
    fav_interests = {i for i in profile.interests}

    emo_tags = _EMOTION_TAGS.get(emotion, _EMOTION_TAGS["neutral"])
    scene_tags = _SCENE_TAGS.get(scene, [])

    liked_titles = liked_titles or set()
    disliked_titles = disliked_titles or set()

    scored = []
    for s in songs:
        tags = set(s["tags"])
        artist = s.get("artist", "")
        score = 0.0
        reasons = []

        # 反馈加权：喜欢的 +1.0，不喜欢的 -2.0
        if s["title"] in liked_titles:
            score += 1.0
            reasons.append("您之前喜欢的")
        if s["title"] in disliked_titles:
            score -= 2.0
            reasons.append("您之前不喜欢的")

        # 老人明确喜欢该歌手/歌名 → 最高优先
        if artist in fav_artists or s["title"] in fav_artists:
            score += 3.0
            reasons.append("您喜欢的")
        if any(t in tags for t in emo_tags):
            score += 1.5
            reasons.append("适合现在的心情")
        if any(t in tags for t in scene_tags):
            score += 1.0
            reasons.append("适合现在的场景")
        if any(t in tags for t in fav_interests):
            score += 0.5
        # 情感标签重叠越多越加分
        overlap = len(tags & set(emo_tags)) + len(tags & set(scene_tags))
        score += overlap * 0.3
        if score > 0:
            scored.append({"title": s["title"], "artist": artist,
                           "tags": s["tags"], "score": round(score, 2),
                           "reason": "，".join(reasons) if reasons else "经典老歌"})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def pick_for_chat(
    profile,
    emotion: str,
    scene: str,
    liked_titles: set = None,
    disliked_titles: set = None,
) -> Dict[str, Any]:
    """给聊天回复用：返回得分最高的一首（随机打破并列），供 Qwen 自然引用。"""
    top = recommend(
        profile, emotion, scene, limit=3,
        liked_titles=liked_titles, disliked_titles=disliked_titles,
    )
    if not top:
        return {}
    best_score = top[0]["score"]
    candidates = [t for t in top if abs(t["score"] - best_score) < 0.001]
    return random.choice(candidates)
