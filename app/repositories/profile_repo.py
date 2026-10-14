"""老人画像 / 家属绑定 / 业务数据 repos。"""
import secrets
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Conversation,
    ElderlyProfile,
    EmotionRecord,
    FamilyElderlyBinding,
    Memory,
)


class ProfileRepo:
    """老人画像 CRUD（异步版，对接 ElderlyProfile ORM）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: str) -> Optional[ElderlyProfile]:
        stmt = select(ElderlyProfile).where(ElderlyProfile.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def upsert(self, user_id: str, data: Dict[str, Any]) -> ElderlyProfile:
        profile = await self.get(user_id)
        if profile is None:
            profile = ElderlyProfile(user_id=user_id, **data)
            self.session.add(profile)
        else:
            for k, v in data.items():
                if hasattr(profile, k):
                    setattr(profile, k, v)
        await self.session.flush()
        return profile

    async def update_partial(self, user_id: str, patch: Dict[str, Any]) -> ElderlyProfile:
        profile = await self.get(user_id)
        if profile is None:
            profile = ElderlyProfile(user_id=user_id, **patch)
            self.session.add(profile)
        else:
            for k, v in patch.items():
                if hasattr(profile, k) and k != "user_id":
                    setattr(profile, k, v)
        await self.session.flush()
        return profile


class FamilyRepo:
    """家属-老人绑定。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bind(
        self,
        family_user_id: str,
        elderly_user_id: str,
        relationship_name: str = "家属",
    ) -> FamilyElderlyBinding:
        binding = FamilyElderlyBinding(
            family_user_id=family_user_id,
            elderly_user_id=elderly_user_id,
            relationship_name=relationship_name,
        )
        self.session.add(binding)
        await self.session.flush()
        return binding

    async def list_elderly(self, family_user_id: str) -> List[str]:
        stmt = select(FamilyElderlyBinding.elderly_user_id).where(
            FamilyElderlyBinding.family_user_id == family_user_id
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def exists(self, family_user_id: str, elderly_user_id: str) -> bool:
        stmt = select(FamilyElderlyBinding.id).where(
            FamilyElderlyBinding.family_user_id == family_user_id,
            FamilyElderlyBinding.elderly_user_id == elderly_user_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def list_family(self, elderly_user_id: str) -> List[str]:
        """反向查询：给定老人 user_id，返回所有绑定的家属 user_id 列表。"""
        stmt = select(FamilyElderlyBinding.family_user_id).where(
            FamilyElderlyBinding.elderly_user_id == elderly_user_id
        )
        return list((await self.session.execute(stmt)).scalars().all())


class MemoryRepo:
    """长期记忆 CRUD（异步版）。embedding 仍以 JSON 存 list[float]。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        user_id: str,
        memory_type: str,
        content: str,
        importance: float = 0.5,
        embedding: Optional[List[float]] = None,
    ) -> int:
        m = Memory(
            user_id=user_id,
            memory_type=memory_type,
            content=content,
            importance=importance,
            embedding=embedding,
        )
        self.session.add(m)
        await self.session.flush()
        return m.id

    async def list_all(self, user_id: str) -> List[Memory]:
        stmt = (
            select(Memory)
            .where(Memory.user_id == user_id)
            .order_by(Memory.importance.desc(), Memory.id.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete(self, user_id: str, memory_id: int) -> bool:
        stmt = delete(Memory).where(
            Memory.id == memory_id, Memory.user_id == user_id
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return (result.rowcount or 0) > 0


class ConversationRepo:
    """对话历史 + 情绪记录（异步版）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        user_id: str,
        role: str,
        content: str,
        current_topic: str = "",
        emotion: str = "neutral",
        scene: str = "conversation",
        intent: str = "",
    ) -> int:
        c = Conversation(
            user_id=user_id,
            role=role,
            content=content,
            current_topic=current_topic,
            emotion=emotion,
            scene=scene,
            intent=intent,
        )
        self.session.add(c)
        await self.session.flush()
        return c.id

    async def recent(self, user_id: str, limit: int = 10) -> List[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.id.desc())
            .limit(limit)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        return list(reversed(rows))  # 时间正序

    async def record_emotion(
        self,
        user_id: str,
        conversation_id: Optional[int],
        emotion: str,
        intensity: float,
    ) -> int:
        r = EmotionRecord(
            user_id=user_id,
            conversation_id=conversation_id,
            emotion=emotion,
            intensity=intensity,
        )
        self.session.add(r)
        await self.session.flush()
        return r.id

    async def list_emotions(self, user_id: str, limit: int = 20) -> List[EmotionRecord]:
        stmt = (
            select(EmotionRecord)
            .where(EmotionRecord.user_id == user_id)
            .order_by(EmotionRecord.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())
