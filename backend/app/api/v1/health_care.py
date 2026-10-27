"""健康关怀路由：用药计划 / 复诊预约 / 血压等记录 / 到期提醒。

老人端（require_elderly）：能增删改自己的计划与记录，能确认提醒。
家属端（require_family + 绑定校验）：只读摘要，不能改老人的任何健康设置
——改了老人却不知道，比不显示更危险。
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_elderly, require_family
from app.db.base import get_db
from app.db.models import (
    Account,
    HealthAppointment,
    HealthMedication,
    HealthRecord,
)
from app.repositories.profile_repo import FamilyRepo
from app.schemas.care import (
    AppointmentUpsert,
    HealthRecordCreate,
    MedicationUpsert,
    ReminderAckRequest,
)
from app.services import health_care as svc

router = APIRouter(prefix="/health-care", tags=["health-care"])
family_router = APIRouter(prefix="/family", tags=["family-health"])


def _parse_date(text: Optional[str]) -> Optional[date]:
    if not text:
        return None
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


async def _get_med(session: AsyncSession, user_id: str, med_id: int) -> HealthMedication:
    med = (await session.execute(
        select(HealthMedication).where(
            HealthMedication.id == med_id,
            HealthMedication.elderly_user_id == user_id,
        )
    )).scalar_one_or_none()
    if med is None:
        raise HTTPException(status_code=404, detail="用药计划不存在")
    return med


async def _get_appt(session: AsyncSession, user_id: str, appt_id: int) -> HealthAppointment:
    appt = (await session.execute(
        select(HealthAppointment).where(
            HealthAppointment.id == appt_id,
            HealthAppointment.elderly_user_id == user_id,
        )
    )).scalar_one_or_none()
    if appt is None:
        raise HTTPException(status_code=404, detail="复诊预约不存在")
    return appt


def _validate_times(req: MedicationUpsert) -> List[str]:
    times = svc.normalize_times(req.times)
    if req.frequency != "as_needed" and not times:
        raise HTTPException(status_code=422, detail="请至少设置一个服药时间，比如 08:00")
    return times


# ---------------------------------------------------------------------------
# 老人端
# ---------------------------------------------------------------------------

@router.get("/overview")
async def overview(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """老人端首页：今天该做什么 + 我的计划 + 最近记录。"""
    now = svc.local_now()
    meds = (await session.execute(
        select(HealthMedication)
        .where(HealthMedication.elderly_user_id == account.user_id)
        .order_by(HealthMedication.active.desc(), HealthMedication.id.desc())
    )).scalars().all()
    appts = (await session.execute(
        select(HealthAppointment)
        .where(
            HealthAppointment.elderly_user_id == account.user_id,
            HealthAppointment.appointment_at >= now - svc.DUE_WINDOW,
        )
        .order_by(HealthAppointment.appointment_at.asc())
        .limit(20)
    )).scalars().all()
    records = (await session.execute(
        select(HealthRecord)
        .where(HealthRecord.elderly_user_id == account.user_id)
        .order_by(HealthRecord.measured_at.desc())
        .limit(10)
    )).scalars().all()

    due = await svc.due_reminders(session, account.user_id, now=now)
    upcoming = await svc.upcoming_reminders(session, account.user_id, hours=24, now=now)
    latest_bp = next((r for r in records if r.record_type == "blood_pressure"), None)

    return {
        "today": now.date().isoformat(),
        "now": now.isoformat(),
        "due": due,
        "upcoming": upcoming,
        "medications": [svc.medication_to_dict(m) for m in meds],
        "appointments": [svc.appointment_to_dict(a) for a in appts],
        "records": [svc.record_to_dict(r) for r in records],
        "latest_blood_pressure": svc.record_to_dict(latest_bp) if latest_bp else None,
    }


# ---------- 强提醒（全局弹窗轮询用，只返回"现在必须处理"的事） ----------

@router.get("/due")
async def due_only(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """只返回当前未确认的提醒。

    前端全局弹窗每 30~60 秒拉一次，不能像 /overview 那样把计划、记录全带上。
    """
    now = svc.local_now()
    items = await svc.due_reminders(session, account.user_id, now=now)
    return {
        "count": len(items),
        "items": items,
        "generated_at": now.isoformat(),
    }


# ---------- 用药 ----------

@router.post("/medications")
async def create_medication(
    req: MedicationUpsert,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    med = HealthMedication(
        elderly_user_id=account.user_id,
        name=req.name.strip(),
        dosage=req.dosage.strip(),
        times=_validate_times(req),
        frequency=req.frequency,
        weekdays=sorted({d for d in req.weekdays if 0 <= d <= 6}),
        start_date=_parse_date(req.start_date),
        end_date=_parse_date(req.end_date),
        note=req.note.strip(),
        active=req.active,
    )
    session.add(med)
    await session.commit()
    await session.refresh(med)
    return svc.medication_to_dict(med)


@router.put("/medications/{med_id}")
async def update_medication(
    med_id: int,
    req: MedicationUpsert,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    med = await _get_med(session, account.user_id, med_id)
    med.name = req.name.strip()
    med.dosage = req.dosage.strip()
    med.times = _validate_times(req)
    med.frequency = req.frequency
    med.weekdays = sorted({d for d in req.weekdays if 0 <= d <= 6})
    med.start_date = _parse_date(req.start_date)
    med.end_date = _parse_date(req.end_date)
    med.note = req.note.strip()
    med.active = req.active
    await session.commit()
    await session.refresh(med)
    return svc.medication_to_dict(med)


@router.delete("/medications/{med_id}")
async def delete_medication(
    med_id: int,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    med = await _get_med(session, account.user_id, med_id)
    await session.delete(med)
    await session.commit()
    return {"deleted": True, "id": med_id}


# ---------- 复诊 ----------

@router.post("/appointments")
async def create_appointment(
    req: AppointmentUpsert,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    at = svc.as_local_naive(req.appointment_at)
    if at is None:
        raise HTTPException(status_code=422, detail="复诊时间格式不正确")
    appt = HealthAppointment(
        elderly_user_id=account.user_id,
        title=req.title.strip(),
        hospital=req.hospital.strip(),
        department=req.department.strip(),
        doctor=req.doctor.strip(),
        appointment_at=at,
        location=req.location.strip(),
        note=req.note.strip(),
        remind_before_minutes=req.remind_before_minutes,
        status=req.status,
    )
    session.add(appt)
    await session.commit()
    await session.refresh(appt)
    return svc.appointment_to_dict(appt)


@router.put("/appointments/{appt_id}")
async def update_appointment(
    appt_id: int,
    req: AppointmentUpsert,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    appt = await _get_appt(session, account.user_id, appt_id)
    at = svc.as_local_naive(req.appointment_at)
    if at is None:
        raise HTTPException(status_code=422, detail="复诊时间格式不正确")
    appt.title = req.title.strip()
    appt.hospital = req.hospital.strip()
    appt.department = req.department.strip()
    appt.doctor = req.doctor.strip()
    appt.appointment_at = at
    appt.location = req.location.strip()
    appt.note = req.note.strip()
    appt.remind_before_minutes = req.remind_before_minutes
    appt.status = req.status
    await session.commit()
    await session.refresh(appt)
    return svc.appointment_to_dict(appt)


@router.post("/appointments/{appt_id}/done")
async def mark_appointment_done(
    appt_id: int,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    appt = await _get_appt(session, account.user_id, appt_id)
    appt.status = "done"
    await session.commit()
    return {"status": "done", "id": appt_id}


@router.delete("/appointments/{appt_id}")
async def delete_appointment(
    appt_id: int,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    appt = await _get_appt(session, account.user_id, appt_id)
    await session.delete(appt)
    await session.commit()
    return {"deleted": True, "id": appt_id}


# ---------- 健康记录 ----------

@router.post("/records")
async def create_record(
    req: HealthRecordCreate,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    if req.record_type == "blood_pressure":
        if req.systolic is None or req.diastolic is None:
            raise HTTPException(status_code=422, detail="血压要同时填高压和低压")
    elif req.value is None:
        raise HTTPException(status_code=422, detail="请填写测量数值")

    measured = svc.as_local_naive(req.measured_at) or svc.local_now()
    record = HealthRecord(
        elderly_user_id=account.user_id,
        record_type=req.record_type,
        systolic=req.systolic,
        diastolic=req.diastolic,
        pulse=req.pulse,
        value=req.value,
        unit=req.unit or svc.RECORD_UNITS.get(req.record_type, ""),
        measured_at=measured,
        note=req.note.strip(),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return svc.record_to_dict(record)


@router.get("/records")
async def list_records(
    limit: int = Query(default=30, ge=1, le=200),
    record_type: Optional[str] = Query(default=None),
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    stmt = select(HealthRecord).where(HealthRecord.elderly_user_id == account.user_id)
    if record_type:
        stmt = stmt.where(HealthRecord.record_type == record_type)
    rows = (await session.execute(
        stmt.order_by(HealthRecord.measured_at.desc()).limit(limit)
    )).scalars().all()
    return {"records": [svc.record_to_dict(r) for r in rows]}


@router.delete("/records/{record_id}")
async def delete_record(
    record_id: int,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    record = (await session.execute(
        select(HealthRecord).where(
            HealthRecord.id == record_id,
            HealthRecord.elderly_user_id == account.user_id,
        )
    )).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    await session.delete(record)
    await session.commit()
    return {"deleted": True, "id": record_id}


# ---------- 提醒确认 ----------

@router.post("/reminders/ack")
async def acknowledge(
    req: ReminderAckRequest,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    try:
        log = await svc.acknowledge_reminder(
            session, account.user_id, req.kind, req.ref_id,
            req.scheduled_for, status=req.status,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    return {
        "status": log.status,
        "id": log.id,
        "kind": log.kind,
        "ref_id": log.ref_id,
        "scheduled_for": log.scheduled_for.isoformat(),
    }


# ---------------------------------------------------------------------------
# 家属端（只读）
# ---------------------------------------------------------------------------

@family_router.get("/elderly/{elderly_id}/health-care")
async def family_health(
    elderly_id: str,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    if not await FamilyRepo(session).exists(account.user_id, elderly_id):
        raise HTTPException(status_code=403, detail="未绑定该老人")
    return await svc.family_health_summary(session, elderly_id)


@family_router.get("/elderly/{elderly_id}/health-care/records")
async def family_health_records(
    elderly_id: str,
    limit: int = Query(default=30, ge=1, le=200),
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    if not await FamilyRepo(session).exists(account.user_id, elderly_id):
        raise HTTPException(status_code=403, detail="未绑定该老人")
    rows = (await session.execute(
        select(HealthRecord)
        .where(HealthRecord.elderly_user_id == elderly_id)
        .order_by(HealthRecord.measured_at.desc())
        .limit(limit)
    )).scalars().all()
    return {"records": [svc.record_to_dict(r) for r in rows]}
