"""老人画像：Pydantic 模型 + SQLite 存取（users 表，profile 存 JSON）。"""
import json
import logging
from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError

from app.db import get_conn

logger = logging.getLogger(__name__)


class ElderlyProfile(BaseModel):
    user_id: str
    name: str = "老人家"
    age: int = Field(default=70, ge=40, le=120)
    gender: str = "未知"
    dialect: str = ""                      # 第 18 轮接方言，先保留字段
    interests: List[str] = Field(default_factory=list)
    favorite_music: List[str] = Field(default_factory=list)
    favorite_stories: List[str] = Field(default_factory=list)
    family: List[str] = Field(default_factory=list)
    life_experience: List[str] = Field(default_factory=list)
    conversation_preferences: Dict[str, Any] = Field(default_factory=dict)
    taboos: List[str] = Field(default_factory=list)

    def prompt_block(self) -> str:
        """转成注入 System Prompt 的中文画像段。空字段不输出，避免误导模型。"""
        lines = [f"- 称呼：{self.name}（{self.age}岁，{self.gender}）"]
        if self.interests:
            lines.append("- 兴趣：" + "、".join(self.interests))
        if self.favorite_music:
            lines.append("- 喜欢的音乐/歌手：" + "、".join(self.favorite_music))
        if self.favorite_stories:
            lines.append("- 喜欢的故事：" + "、".join(self.favorite_stories))
        if self.family:
            lines.append("- 家人：" + "、".join(self.family))
        if self.life_experience:
            lines.append("- 人生经历：" + "；".join(self.life_experience))
        if self.dialect:
            lines.append(f"- 方言习惯：{self.dialect}")
        if self.taboos:
            lines.append("- 忌讳（不要主动提及）：" + "、".join(self.taboos))
        prefs = self.conversation_preferences
        if prefs:
            lines.append("- 交流偏好：" + json.dumps(prefs, ensure_ascii=False))
        return "\n".join(lines)


DEFAULT_PROFILE: Dict[str, Any] = {
    "user_id": "elderly_001",
    "name": "王阿姨",
    "age": 72,
    "gender": "女",
    "dialect": "",
    "interests": ["唱歌", "听老歌"],
    "favorite_music": ["邓丽君"],
    "favorite_stories": [],
    "family": ["女儿小芳"],
    "life_experience": ["年轻时在纺织厂工作"],
    "conversation_preferences": {"回复长度": "短", "语速语气": "温和耐心"},
    "taboos": [],
}


class ProfileStore:
    """画像 CRUD。首次访问某 user_id 时自动按默认档案建档。"""

    def get(self, user_id: str) -> ElderlyProfile:
        with get_conn() as conn:
            # 优先从新表 elderly_profiles 读（前端保存的地方）
            row = conn.execute(
                "SELECT name, age, gender, dialect, interests, favorite_music, "
                "favorite_stories, family, life_experience, conversation_preferences, taboos "
                "FROM elderly_profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row is not None:
                # 从新表读到了，转成 ElderlyProfile
                data = {
                    "user_id": user_id,
                    "name": row["name"] or "老人家",
                    "age": row["age"] or 70,
                    "gender": row["gender"] or "未知",
                    "dialect": row["dialect"] or "",
                    "interests": json.loads(row["interests"]) if row["interests"] else [],
                    "favorite_music": json.loads(row["favorite_music"]) if row["favorite_music"] else [],
                    "favorite_stories": json.loads(row["favorite_stories"]) if row["favorite_stories"] else [],
                    "family": json.loads(row["family"]) if row["family"] else [],
                    "life_experience": json.loads(row["life_experience"]) if row["life_experience"] else [],
                    "conversation_preferences": json.loads(row["conversation_preferences"]) if row["conversation_preferences"] else {},
                    "taboos": json.loads(row["taboos"]) if row["taboos"] else [],
                }
                return ElderlyProfile.model_validate(data)

            # 新表没有，fallback 到旧表 users
            row = conn.execute(
                "SELECT profile FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row is None:
                data = dict(DEFAULT_PROFILE)
                data["user_id"] = user_id
                # 演示档案只对预置 elderly_001 生效，新用户给干净默认值
                if user_id != "elderly_001":
                    data.update({
                        "name": "老人家", "age": 70, "gender": "未知",
                        "interests": [], "favorite_music": [], "favorite_stories": [],
                        "family": [], "life_experience": [],
                        "conversation_preferences": {}, "taboos": [],
                    })
                self.save(data)
                return ElderlyProfile.model_validate(data)
            try:
                return ElderlyProfile.model_validate(json.loads(row["profile"]))
            except (json.JSONDecodeError, ValidationError) as e:
                logger.error("画像数据损坏 user_id=%s: %s，返回默认画像", user_id, e)
                return ElderlyProfile.model_validate(
                    {**DEFAULT_PROFILE, "user_id": user_id}
                )

    def save(self, data: Dict[str, Any]) -> ElderlyProfile:
        profile = ElderlyProfile.model_validate(data)
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO users (user_id, profile)
                   VALUES (?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     profile = excluded.profile,
                     updated_at = datetime('now', 'localtime')""",
                (profile.user_id, profile.model_dump_json()),
            )
        return profile

    def update_partial(self, user_id: str, patch: Dict[str, Any]) -> ElderlyProfile:
        current = self.get(user_id).model_dump()
        current.update({k: v for k, v in patch.items() if k != "user_id"})
        return self.save(current)
