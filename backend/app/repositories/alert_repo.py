"""告警数据访问层。"""
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FamilyAlert

logger = logging.getLogger(__name__)


class AlertRepo:
    """家属告警 CRUD。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        elderly_user_id: str,
        alert_type: str,
        severity: str,
        title: str,
        detail: str = "",
    ) -> int:
        """创建告警。"""
        alert = FamilyAlert(
            elderly_user_id=elderly_user_id,
            alert_type=alert_type,
            severity=severity,
            title=title,
            detail=detail,
        )
        self.session.add(alert)
        await self.session.flush()
        return alert.id

    async def list_by_elderly(
        self, elderly_user_id: str, limit: int = 50
    ) -> List[FamilyAlert]:
        """查询老人的告警列表。"""
        stmt = (
            select(FamilyAlert)
            .where(FamilyAlert.elderly_user_id == elderly_user_id)
            .order_by(FamilyAlert.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_families(
        self, family_user_ids: List[str], limit: int = 50
    ) -> List[FamilyAlert]:
        """查询多个家属绑定的所有老人的告警。"""
        if not family_user_ids:
            return []
        
        # 先查询这些家属绑定的老人
        from app.db.models import FamilyElderlyBinding
        stmt = select(FamilyElderlyBinding.elderly_user_id).where(
            FamilyElderlyBinding.family_user_id.in_(family_user_ids)
        )
        result = await self.session.execute(stmt)
        elderly_ids = [row[0] for row in result.all()]
        
        if not elderly_ids:
            return []
        
        # 查询这些老人的告警
        stmt = (
            select(FamilyAlert)
            .where(FamilyAlert.elderly_user_id.in_(elderly_ids))
            .order_by(FamilyAlert.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def acknowledge(self, alert_id: int, family_user_id: str) -> bool:
        """确认告警。"""
        stmt = (
            update(FamilyAlert)
            .where(FamilyAlert.id == alert_id)
            .values(
                is_acknowledged=True,
                acknowledged_by=family_user_id,
                acknowledged_at=datetime.now(),
            )
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def check_recent_alert(
        self, elderly_user_id: str, alert_type: str, hours: int = 24
    ) -> bool:
        """检查最近 N 小时内是否已有同类型告警（去重）。"""
        from datetime import timedelta
        from sqlalchemy import func
        
        threshold = datetime.now() - timedelta(hours=hours)
        stmt = (
            select(func.count())
            .select_from(FamilyAlert)
            .where(
                FamilyAlert.elderly_user_id == elderly_user_id,
                FamilyAlert.alert_type == alert_type,
                FamilyAlert.created_at >= threshold,
            )
        )
        result = await self.session.execute(stmt)
        count = result.scalar()
        return count > 0
