"""家人留言数据访问层（家属 ↔ 老人 双向互动）。

方向由 sender_role 决定：
- sender_role='family' ：家属(family_user_id) → 老人(elderly_user_id)，接收方=老人
- sender_role='elderly'：老人(elderly_user_id) → 家属(family_user_id)，接收方=家属
is_read / reaction 描述接收方的读取与回应。
"""
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FamilyMessage

logger = logging.getLogger(__name__)


class FamilyMessageRepo:
    """家人留言的 CRUD（双向）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        family_user_id: str,
        elderly_user_id: str,
        content: str,
        category: str = "greeting",
        sender_role: str = "family",
    ) -> int:
        """创建一条留言，返回 id。sender_role 决定方向。"""
        msg = FamilyMessage(
            family_user_id=family_user_id,
            elderly_user_id=elderly_user_id,
            content=content,
            category=category,
            sender_role=sender_role,
        )
        self.session.add(msg)
        await self.session.flush()
        return msg.id

    async def count_between(self, elderly_user_id: str, since: datetime) -> int:
        """某时间点之后与该老人的双向留言总数（不含系统日报）。

        日报（category='digest'）是系统以老人名义推给家属的陪伴报告，
        不算「家人互动」，否则每天一条日报会把联结因子刷满。
        """
        stmt = (
            select(func.count())
            .select_from(FamilyMessage)
            .where(
                FamilyMessage.elderly_user_id == elderly_user_id,
                FamilyMessage.created_at >= since,
                FamilyMessage.category != "digest",
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_for_elderly(
        self, elderly_user_id: str, limit: int = 50
    ) -> List[FamilyMessage]:
        """老人收件箱：家属发给我的。"""
        stmt = (
            select(FamilyMessage)
            .where(
                FamilyMessage.elderly_user_id == elderly_user_id,
                FamilyMessage.sender_role == "family",
            )
            .order_by(FamilyMessage.created_at.desc(), FamilyMessage.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_sent_by_elderly(
        self, elderly_user_id: str, limit: int = 50
    ) -> List[FamilyMessage]:
        """老人发给家人的留言。"""
        stmt = (
            select(FamilyMessage)
            .where(
                FamilyMessage.elderly_user_id == elderly_user_id,
                FamilyMessage.sender_role == "elderly",
            )
            .order_by(FamilyMessage.created_at.desc(), FamilyMessage.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_sent_by_family(
        self, family_user_id: str, elderly_user_id: str, limit: int = 50
    ) -> List[FamilyMessage]:
        """家属发给某位老人的留言。"""
        stmt = (
            select(FamilyMessage)
            .where(
                FamilyMessage.family_user_id == family_user_id,
                FamilyMessage.elderly_user_id == elderly_user_id,
                FamilyMessage.sender_role == "family",
            )
            .order_by(FamilyMessage.created_at.desc(), FamilyMessage.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_received_by_family(
        self, family_user_id: str, elderly_user_id: str, limit: int = 50
    ) -> List[FamilyMessage]:
        """家属收件箱：某位老人发给我的。"""
        stmt = (
            select(FamilyMessage)
            .where(
                FamilyMessage.family_user_id == family_user_id,
                FamilyMessage.elderly_user_id == elderly_user_id,
                FamilyMessage.sender_role == "elderly",
            )
            .order_by(FamilyMessage.created_at.desc(), FamilyMessage.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_dog_relays(
        self, elderly_user_id: str, limit: int = 50
    ) -> List[FamilyMessage]:
        """小狗传话记录（category='dog_relay'，家属→老人），按时间倒序。

        陪伴日志用：只读 category 与已读状态，不涉及其它留言类型。
        """
        stmt = (
            select(FamilyMessage)
            .where(
                FamilyMessage.elderly_user_id == elderly_user_id,
                FamilyMessage.sender_role == "family",
                FamilyMessage.category == "dog_relay",
            )
            .order_by(FamilyMessage.created_at.desc(), FamilyMessage.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_pending_dog_relays(
        self, elderly_user_id: str, limit: int = 5
    ) -> List[FamilyMessage]:
        """老人端待补播的小狗传话（category='dog_relay' 且未读），按时间正序。

        用于老人发作时不在线的场景：登录后拉取这条历史传话补播一次。
        """
        stmt = (
            select(FamilyMessage)
            .where(
                FamilyMessage.elderly_user_id == elderly_user_id,
                FamilyMessage.sender_role == "family",
                FamilyMessage.category == "dog_relay",
                FamilyMessage.is_read.is_(False),
            )
            .order_by(FamilyMessage.id.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def unread_for_elderly(self, elderly_user_id: str) -> int:
        """老人未读（家属发我的）。"""
        stmt = (
            select(func.count())
            .select_from(FamilyMessage)
            .where(
                FamilyMessage.elderly_user_id == elderly_user_id,
                FamilyMessage.sender_role == "family",
                FamilyMessage.is_read.is_(False),
            )
        )
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def unread_for_family(self, family_user_id: str) -> int:
        """家属未读（老人发我的）。"""
        stmt = (
            select(func.count())
            .select_from(FamilyMessage)
            .where(
                FamilyMessage.family_user_id == family_user_id,
                FamilyMessage.sender_role == "elderly",
                FamilyMessage.is_read.is_(False),
            )
        )
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def mark_read(
        self, message_id: int, receiver_user_id: str, reaction: Optional[str] = None
    ) -> Optional[FamilyMessage]:
        """接收方标记已读 + 回应。仅当前用户是该消息接收方时生效。

        成功返回被更新的消息（供推送事件用），否则返回 None。
        """
        msg = await self.session.get(FamilyMessage, message_id)
        if msg is None:
            return None
        receiver = (
            msg.elderly_user_id if msg.sender_role == "family" else msg.family_user_id
        )
        if receiver != receiver_user_id:
            return None
        msg.is_read = True
        msg.read_at = datetime.now()
        if reaction:
            msg.reaction = reaction
        await self.session.flush()
        return msg
