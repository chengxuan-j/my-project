"""健康关怀业务层：用药计划 / 复诊 / 健康记录 / 提醒到期计算。

三条原则：

1. **到期由数据算，不靠"发过没发过"**。
   定时任务可能没跑（开发环境默认不开调度器），也可能重启丢了一次扫描。
   所以 `/health-care/overview` 每次都重新按规则算一遍"现在有什么该提醒"，
   流水表只用来记"发过 / 老人确认过"，不作为是否到期的唯一依据。
   这样即便调度器一直没启动，老人打开页面照样看得到该吃的药。

2. **同一件事只提醒一次**。
   (kind, ref_id, scheduled_for) 唯一索引兜底；定时任务反复扫也只会写一条。

3. **不诊断**。
   血压只给"参考区间"和"记下来就好"的建议，绝不说"你有高血压"。
   这和陪伴 prompt 里"不进行医疗诊断"是同一条底线。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    HealthAppointment,
    HealthMedication,
    HealthRecord,
    HealthReminderLog,
)

logger = logging.getLogger(__name__)

# 一次提醒的"有效窗口"：过了这么久还没确认，就不再追着提醒了。
# 吃药漏了一顿，中午再弹一次是关心；晚上十点还弹早上八点的药，是打扰。
DUE_WINDOW = timedelta(hours=12)

RECORD_LABELS = {
    "blood_pressure": "血压",
    "blood_sugar": "血糖",
    "weight": "体重",
    "pulse": "心率",
    "temperature": "体温",
}

RECORD_UNITS = {
    "blood_sugar": "mmol/L",
    "weight": "kg",
    "pulse": "次/分",
    "temperature": "℃",
}


# ---------------------------------------------------------------------------
# 时间工具
# ---------------------------------------------------------------------------

def local_now() -> datetime:
    """当前本地时间（naive）。全模块统一用它，避免 aware/naive 比较报错。"""
    return datetime.now().replace(microsecond=0)


def as_local_naive(value: Any) -> Optional[datetime]:
    """把前端传来的 ISO 串 / datetime 收敛成 naive 本地时间。

    - 带时区的先转成本地时区再摘掉 tzinfo；
    - 纯日期按当天 09:00 处理（老人填"某天"时给个合理默认）。
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, time(hour=9))
    else:
        text = str(value).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            # 只给了日期
            try:
                dt = datetime.combine(date.fromisoformat(text[:10]), time(hour=9))
            except ValueError:
                return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.replace(microsecond=0)


def _minute_key(dt: datetime) -> datetime:
    """秒/微秒清零：同一条提醒在不同链路算出来的 key 必须一致。"""
    return dt.replace(second=0, microsecond=0)


def _parse_hhmm(text: str) -> Optional[time]:
    try:
        hour, minute = str(text).strip().split(":")[:2]
        return time(hour=int(hour), minute=int(minute))
    except (ValueError, AttributeError):
        return None


def normalize_times(raw: Optional[Iterable[Any]]) -> List[str]:
    """把 ["8:00", "20:0", "08:00"] 收敛成 ["08:00", "20:00"]（去重排序）。"""
    seen: List[str] = []
    for item in raw or []:
        parsed = _parse_hhmm(str(item))
        if parsed is None:
            continue
        text = parsed.strftime("%H:%M")
        if text not in seen:
            seen.append(text)
    return sorted(seen)


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------

def medication_to_dict(m: HealthMedication) -> Dict[str, Any]:
    return {
        "id": m.id,
        "name": m.name,
        "dosage": m.dosage or "",
        "times": normalize_times(m.times),
        "frequency": m.frequency or "daily",
        "weekdays": sorted(m.weekdays or []),
        "start_date": m.start_date.isoformat() if m.start_date else "",
        "end_date": m.end_date.isoformat() if m.end_date else "",
        "note": m.note or "",
        "active": bool(m.active),
        "created_at": m.created_at.isoformat() if m.created_at else "",
    }


def appointment_to_dict(a: HealthAppointment) -> Dict[str, Any]:
    at = a.appointment_at
    return {
        "id": a.id,
        "title": a.title,
        "hospital": a.hospital or "",
        "department": a.department or "",
        "doctor": a.doctor or "",
        "appointment_at": at.isoformat() if at else "",
        "location": a.location or "",
        "note": a.note or "",
        "remind_before_minutes": a.remind_before_minutes,
        "status": a.status,
        "created_at": a.created_at.isoformat() if a.created_at else "",
    }


def bp_level(systolic: Optional[int], diastolic: Optional[int]) -> Dict[str, str]:
    """血压参考区间（不做诊断，只标明离常见区间远不远）。"""
    if not systolic or not diastolic:
        return {"key": "unknown", "label": "待补全", "color": "gray", "advice": ""}
    if systolic < 90 or diastolic < 60:
        return {
            "key": "low", "label": "偏低", "color": "blue",
            "advice": "如果头晕、没力气，先坐下歇会儿，跟家里人说一声。",
        }
    if systolic >= 160 or diastolic >= 100:
        return {
            "key": "high", "label": "偏高较多", "color": "red",
            "advice": "先安静坐五分钟再量一次；连续几天这样，记得跟医生说。",
        }
    if systolic >= 140 or diastolic >= 90:
        return {
            "key": "elevated", "label": "偏高", "color": "orange",
            "advice": "记下来就好，连着几天偏高，可以跟家里人提一句。",
        }
    if systolic >= 120 or diastolic >= 80:
        return {
            "key": "normal_high", "label": "正常偏高", "color": "amber",
            "advice": "在常见区间里偏高一点，清淡点、少盐，继续记着看。",
        }
    return {"key": "normal", "label": "正常", "color": "green", "advice": ""}


def record_to_dict(r: HealthRecord) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": r.id,
        "record_type": r.record_type,
        "record_label": RECORD_LABELS.get(r.record_type, r.record_type),
        "systolic": r.systolic,
        "diastolic": r.diastolic,
        "pulse": r.pulse,
        "value": r.value,
        "unit": r.unit or RECORD_UNITS.get(r.record_type, ""),
        "measured_at": r.measured_at.isoformat() if r.measured_at else "",
        "note": r.note or "",
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }
    if r.record_type == "blood_pressure":
        data["level"] = bp_level(r.systolic, r.diastolic)
    else:
        data["level"] = {"key": "recorded", "label": "已记录", "color": "gray", "advice": ""}
    return data


# ---------------------------------------------------------------------------
# 用药规则 → 某个日期是否该吃、几点吃
# ---------------------------------------------------------------------------

def medication_occurs_on(med: HealthMedication, day: date) -> bool:
    if not med.active:
        return False
    if med.start_date and day < med.start_date:
        return False
    if med.end_date and day > med.end_date:
        return False
    if (med.frequency or "daily") == "as_needed":
        return False  # 按需服药不做定时提醒，避免老人被无谓打扰
    if (med.frequency or "daily") == "weekly":
        weekdays = med.weekdays or []
        if weekdays and day.weekday() not in weekdays:
            return False
    return True


def medication_dose_times(med: HealthMedication, day: date) -> List[datetime]:
    """某天的所有服药时间点。"""
    if not medication_occurs_on(med, day):
        return []
    result: List[datetime] = []
    for text in normalize_times(med.times):
        t = _parse_hhmm(text)
        if t is not None:
            result.append(datetime.combine(day, t))
    return sorted(result)


# ---------------------------------------------------------------------------
# 到期提醒
# ---------------------------------------------------------------------------

async def _log_index(
    session: AsyncSession, user_id: str, since: datetime
) -> Dict[Tuple[str, int, str], HealthReminderLog]:
    stmt = select(HealthReminderLog).where(
        HealthReminderLog.elderly_user_id == user_id,
        HealthReminderLog.scheduled_for >= since,
    )
    rows = (await session.execute(stmt)).scalars().all()
    index: Dict[Tuple[str, int, str], HealthReminderLog] = {}
    for row in rows:
        key = (row.kind, int(row.ref_id), _minute_key(row.scheduled_for).isoformat())
        index[key] = row
    return index


def _due_item(
    kind: str, ref_id: int, title: str, detail: str, scheduled_for: datetime,
    now: datetime, log: Optional[HealthReminderLog],
) -> Dict[str, Any]:
    minutes = int((scheduled_for - now).total_seconds() // 60)
    return {
        "key": f"{kind}:{ref_id}:{_minute_key(scheduled_for).isoformat()}",
        "kind": kind,
        "ref_id": ref_id,
        "title": title,
        "detail": detail,
        "scheduled_for": scheduled_for.isoformat(),
        "minutes_until": minutes,
        "overdue_minutes": max(0, -minutes),
        "log_status": log.status if log else "",
        "log_id": log.id if log else None,
        "message": log.message if log else "",
    }


async def due_reminders(
    session: AsyncSession, user_id: str, now: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """当前该提醒、但老人还没确认的事项（含已发过未确认的）。"""
    now = _minute_key(now or local_now())
    window_start = now - timedelta(days=2)
    logs = await _log_index(session, user_id, window_start)
    items: List[Dict[str, Any]] = []

    meds = (
        await session.execute(
            select(HealthMedication).where(
                HealthMedication.elderly_user_id == user_id,
                HealthMedication.active.is_(True),
            )
        )
    ).scalars().all()
    for med in meds:
        for day in (now.date() - timedelta(days=1), now.date()):
            for scheduled in medication_dose_times(med, day):
                if scheduled > now or now - scheduled > DUE_WINDOW:
                    continue
                key = ("medication", med.id, _minute_key(scheduled).isoformat())
                log = logs.get(key)
                if log and log.status == "acknowledged":
                    continue
                detail = " · ".join(filter(None, [med.dosage, med.note]))
                items.append(_due_item(
                    "medication", med.id, f"该吃{med.name}", detail, scheduled, now, log,
                ))

    appts = (
        await session.execute(
            select(HealthAppointment).where(
                HealthAppointment.elderly_user_id == user_id,
                HealthAppointment.status == "scheduled",
            )
        )
    ).scalars().all()
    for appt in appts:
        at = _minute_key(appt.appointment_at)
        remind_at = at - timedelta(minutes=max(0, appt.remind_before_minutes or 0))
        if remind_at > now or now - at > DUE_WINDOW:
            continue
        key = ("appointment", appt.id, at.isoformat())
        log = logs.get(key)
        if log and log.status == "acknowledged":
            continue
        detail = " · ".join(filter(None, [appt.hospital, appt.department, appt.location]))
        items.append(_due_item(
            "appointment", appt.id, f"别忘了：{appt.title}", detail, at, now, log,
        ))

    items.sort(key=lambda x: x["scheduled_for"])
    return items


async def upcoming_reminders(
    session: AsyncSession, user_id: str, hours: int = 24,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """未来 N 小时内、还没到点的提醒（给老人一个"接下来要做什么"的预览）。"""
    now = _minute_key(now or local_now())
    horizon = now + timedelta(hours=hours)
    items: List[Dict[str, Any]] = []

    meds = (
        await session.execute(
            select(HealthMedication).where(
                HealthMedication.elderly_user_id == user_id,
                HealthMedication.active.is_(True),
            )
        )
    ).scalars().all()
    for med in meds:
        for day in (now.date(), now.date() + timedelta(days=1)):
            for scheduled in medication_dose_times(med, day):
                if scheduled <= now or scheduled > horizon:
                    continue
                items.append({
                    "key": f"medication:{med.id}:{_minute_key(scheduled).isoformat()}",
                    "kind": "medication",
                    "ref_id": med.id,
                    "title": f"该吃{med.name}",
                    "detail": med.dosage or "",
                    "scheduled_for": scheduled.isoformat(),
                    "minutes_until": int((scheduled - now).total_seconds() // 60),
                })

    appts = (
        await session.execute(
            select(HealthAppointment).where(
                HealthAppointment.elderly_user_id == user_id,
                HealthAppointment.status == "scheduled",
            )
        )
    ).scalars().all()
    for appt in appts:
        at = _minute_key(appt.appointment_at)
        if at <= now or at > horizon:
            continue
        items.append({
            "key": f"appointment:{appt.id}:{at.isoformat()}",
            "kind": "appointment",
            "ref_id": appt.id,
            "title": f"复诊：{appt.title}",
            "detail": " · ".join(filter(None, [appt.hospital, appt.department])),
            "scheduled_for": at.isoformat(),
            "minutes_until": int((at - now).total_seconds() // 60),
        })

    items.sort(key=lambda x: x["scheduled_for"])
    return items


async def acknowledge_reminder(
    session: AsyncSession,
    user_id: str,
    kind: str,
    ref_id: int,
    scheduled_for: Any,
    status: str = "acknowledged",
) -> HealthReminderLog:
    """老人点"吃过了 / 知道了"：写流水（已有则更新状态）。"""
    scheduled = as_local_naive(scheduled_for)
    if scheduled is None:
        raise ValueError("提醒时间格式不正确")
    scheduled = _minute_key(scheduled)

    if kind == "medication":
        ref = (await session.execute(
            select(HealthMedication).where(
                HealthMedication.id == ref_id,
                HealthMedication.elderly_user_id == user_id,
            )
        )).scalar_one_or_none()
        message = f"吃药：{ref.name}" if ref else "吃药"
    elif kind == "appointment":
        ref = (await session.execute(
            select(HealthAppointment).where(
                HealthAppointment.id == ref_id,
                HealthAppointment.elderly_user_id == user_id,
            )
        )).scalar_one_or_none()
        message = f"复诊：{ref.title}" if ref else "复诊"
    else:
        raise ValueError("kind 只支持 medication / appointment")
    if ref is None:
        raise LookupError("提醒对应的记录不存在")

    log = (await session.execute(
        select(HealthReminderLog).where(
            HealthReminderLog.kind == kind,
            HealthReminderLog.ref_id == ref_id,
            HealthReminderLog.scheduled_for == scheduled,
        )
    )).scalar_one_or_none()
    if log is None:
        log = HealthReminderLog(
            elderly_user_id=user_id, kind=kind, ref_id=ref_id,
            scheduled_for=scheduled, status=status, message=message,
        )
        session.add(log)
        await session.flush()
    log.status = status
    log.acknowledged_at = local_now() if status == "acknowledged" else None
    await session.flush()
    return log


# ---------------------------------------------------------------------------
# 依从率（家属端）：最近 N 天该吃几次、确认了几次
# ---------------------------------------------------------------------------

async def adherence_stats(
    session: AsyncSession, user_id: str, days: int = 7,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = _minute_key(now or local_now())
    start_day = now.date() - timedelta(days=days - 1)

    meds = (
        await session.execute(
            select(HealthMedication).where(
                HealthMedication.elderly_user_id == user_id,
            )
        )
    ).scalars().all()

    expected_keys: set[str] = set()
    for med in meds:
        day = start_day
        while day <= now.date():
            for scheduled in medication_dose_times(med, day):
                if scheduled <= now:
                    expected_keys.add(f"{med.id}:{_minute_key(scheduled).isoformat()}")
            day += timedelta(days=1)

    since = datetime.combine(start_day, time.min)
    logs = (
        await session.execute(
            select(HealthReminderLog).where(
                HealthReminderLog.elderly_user_id == user_id,
                HealthReminderLog.kind == "medication",
                HealthReminderLog.status == "acknowledged",
                HealthReminderLog.scheduled_for >= since,
            )
        )
    ).scalars().all()
    acked = {
        f"{log.ref_id}:{_minute_key(log.scheduled_for).isoformat()}" for log in logs
    }

    expected = len(expected_keys)
    done = len(expected_keys & acked)
    return {
        "days": days,
        "expected": expected,
        "acknowledged": done,
        "missed": max(0, expected - done),
        "rate": round(done / expected, 2) if expected else None,
    }


async def family_health_summary(
    session: AsyncSession, user_id: str, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """家属端只读健康摘要：不需要给家属看每一条提醒流水，给趋势就够。"""
    now = _minute_key(now or local_now())

    meds = (
        await session.execute(
            select(HealthMedication).where(
                HealthMedication.elderly_user_id == user_id,
                HealthMedication.active.is_(True),
            ).order_by(HealthMedication.id.desc())
        )
    ).scalars().all()
    appts = (
        await session.execute(
            select(HealthAppointment).where(
                HealthAppointment.elderly_user_id == user_id,
                HealthAppointment.status == "scheduled",
                HealthAppointment.appointment_at >= now - timedelta(hours=12),
            ).order_by(HealthAppointment.appointment_at.asc()).limit(5)
        )
    ).scalars().all()
    records = (
        await session.execute(
            select(HealthRecord).where(
                HealthRecord.elderly_user_id == user_id,
            ).order_by(HealthRecord.measured_at.desc()).limit(10)
        )
    ).scalars().all()

    latest_bp = next(
        (r for r in records if r.record_type == "blood_pressure"), None
    )
    return {
        "user_id": user_id,
        "medications": [medication_to_dict(m) for m in meds],
        "appointments": [appointment_to_dict(a) for a in appts],
        "records": [record_to_dict(r) for r in records],
        "latest_blood_pressure": record_to_dict(latest_bp) if latest_bp else None,
        "adherence": await adherence_stats(session, user_id, days=7, now=now),
        "due": await due_reminders(session, user_id, now=now),
        "generated_at": now.isoformat(),
    }
