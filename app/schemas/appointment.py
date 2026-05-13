from pydantic import BaseModel, model_validator
from typing import Optional
from datetime import datetime, date
import uuid


class AppointmentCreate(BaseModel):
    client_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    session_type: Optional[str] = "Individual"
    override_price: Optional[float] = None
    session_notes: Optional[str] = None
    tax_exempt: Optional[bool] = None  # None = use client default

    @model_validator(mode="after")
    def validate_times(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class RecurringAppointmentCreate(BaseModel):
    client_id: uuid.UUID
    recurrence_type: str          # daily, weekly, biweekly, monthly
    start_date: date
    end_date: Optional[date] = None
    occurrence_count: Optional[int] = None
    start_hour: int = 10          # 24h local hour (therapist's timezone)
    start_minute: int = 0
    duration_minutes: int = 50
    session_type: Optional[str] = "Individual"
    override_price: Optional[float] = None
    tax_exempt: Optional[bool] = None  # None = use client default

    @model_validator(mode="after")
    def validate_end(self):
        if not self.end_date and not self.occurrence_count:
            raise ValueError("Provide either end_date or occurrence_count")
        if self.occurrence_count and self.occurrence_count > 104:
            raise ValueError("Maximum 104 occurrences (2 years)")
        return self


class AppointmentUpdate(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    session_type: Optional[str] = None
    override_price: Optional[float] = None
    session_notes: Optional[str] = None
    cancellation_reason: Optional[str] = None
    tax_exempt: Optional[bool] = None


class AppointmentStatusUpdate(BaseModel):
    status: str  # completed, canceled, no_show
    cancellation_reason: Optional[str] = None
    session_notes: Optional[str] = None


class AppointmentResponse(BaseModel):
    id: uuid.UUID
    therapist_id: uuid.UUID
    client_id: uuid.UUID
    client_name: Optional[str] = None
    therapist_name: Optional[str] = None
    start_time: datetime
    end_time: datetime
    status: str
    session_type: Optional[str]
    override_price: Optional[float]
    effective_price: Optional[float]
    google_event_id: Optional[str]
    completed_at: Optional[datetime]
    canceled_at: Optional[datetime]
    session_notes: Optional[str]
    has_invoice: bool
    billed: bool = False
    recurrence_id: Optional[uuid.UUID] = None
    tax_exempt: Optional[bool] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AvailabilityRequest(BaseModel):
    date: str  # YYYY-MM-DD
    duration_minutes: int = 50
