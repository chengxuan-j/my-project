"""故事推荐：data/stories.json + 情绪/兴趣匹配。

设计文档第二十节：支持推荐故事、讲故事、按情绪推荐、按兴趣推荐。
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

STORIES_PATH = os.path.join(BASE_DIR, "data", "stories.json")


def _load() -> List[Dict[str, Any]]:
    try:
        with open(STORIES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("读取 stories.json 失败: %s", e)
        return []


def _match_score(story: Dict[str, Any], emotion: str,
                 interests: List[str]) -> float:
    score = 0.0
    moods = set(story.get("mood", []))
    if emotion in moods:
        score += 2.0
    if emotion == "neutral" and "neutral" in moods:
        score += 1.0
    tags = set(story.get("tags", []))
    for interest in interests:
        if any(interest in t for t in tags) or any(t in interest for t in tags):
            score += 1.5
    # 短故事在陪伴场景更合适，轻微加分
    if story.get("length") == "short":
        score += 0.2
    return score


def recommend(
    profile,
    emotion: str,
    limit: int = 3,
    liked_titles: set = None,
    disliked_titles: set = None,
) -> List[Dict[str, Any]]:
    stories = _load()
    if not stories:
        return []
    interests = profile.interests

    liked_titles = liked_titles or set()
    disliked_titles = disliked_titles or set()

    scored = []
    for s in stories:
        score = _match_score(s, emotion, interests)
        # 反馈加权
        if s["title"] in liked_titles:
            score += 1.0
        if s["title"] in disliked_titles:
            score -= 2.0
        if score > 0:
            scored.append({**s, "score": round(score, 2)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def get_story(title: str) -> Optional[Dict[str, Any]]:
    for s in _load():
        if s["title"] == title:
            return s
    return None


def list_all() -> List[Dict[str, Any]]:
    return _load()
