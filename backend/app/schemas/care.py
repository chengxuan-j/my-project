"""健康关怀 / 时光信笺 / 方言设置的请求模型。"""

from typing import List, Optional

from pydantic import BaseModel, Field


# ---------- 用药 ----------

class MedicationUpsert(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    dosage: str = Field(default="", max_length=64)
    times: List[str] = Field(default_factory=list, max_length=12)
    frequency: str = Field(default="daily", pattern="^(daily|weekly|as_needed)$")
    weekdays: List[int] = Field(default_factory=list, max_length=7)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    note: str = Field(default="", max_length=200)
    active: bool = True


# ---------- 复诊 ----------

class AppointmentUpsert(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    hospital: str = Field(default="", max_length=100)
    department: str = Field(default="", max_length=64)
    doctor: str = Field(default="", max_length=64)
    appointment_at: str = Field(..., min_length=1)
    location: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=200)
    remind_before_minutes: int = Field(default=1440, ge=0, le=10080)
    status: str = Field(default="scheduled", pattern="^(scheduled|done|cancelled)$")


# ---------- 健康记录 ----------

class HealthRecordCreate(BaseModel):
    record_type: str = Field(
        default="blood_pressure",
        pattern="^(blood_pressure|blood_sugar|weight|pulse|temperature)$",
    )
    systolic: Optional[int] = Field(default=None, ge=40, le=300)
    diastolic: Optional[int] = Field(default=None, ge=20, le=200)
    pulse: Optional[int] = Field(default=None, ge=20, le=250)
    value: Optional[float] = Field(default=None, ge=0, le=1000)
    unit: str = Field(default="", max_length=16)
    measured_at: Optional[str] = None
    note: str = Field(default="", max_length=200)


class ReminderAckRequest(BaseModel):
    kind: str = Field(..., pattern="^(medication|appointment)$")
    ref_id: int
    scheduled_for: str = Field(..., min_length=1)
    status: str = Field(default="acknowledged", pattern="^(acknowledged|skipped)$")


# ---------- 时光信笺 ----------

class LetterCreate(BaseModel):
    title: str = Field(default="", max_length=100)
    content: str = Field(..., min_length=1, max_length=4000)
    recipient_type: str = Field(default="self", pattern="^(self|family)$")
    recipient_name: str = Field(default="", max_length=64)
    deliver_at: str = Field(..., min_length=1)
    visibility: str = Field(default="private", pattern="^(private|family)$")


class LetterUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=100)
    content: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    recipient_type: Optional[str] = Field(default=None, pattern="^(self|family)$")
    recipient_name: Optional[str] = Field(default=None, max_length=64)
    deliver_at: Optional[str] = None
    visibility: Optional[str] = Field(default=None, pattern="^(private|family)$")


# ---------- 方言 ----------

class DialectSettingRequest(BaseModel):
    enabled: bool = False
    dialect: str = Field(default="普通话", max_length=32)
