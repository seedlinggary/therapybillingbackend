"""
Appointments CRUD — therapist-scoped with Google Calendar integration.
"""
import calendar as cal_mod
from typing import List, Optional
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.core.deps import get_current_therapist, get_current_client
from app.models.therapist import Therapist
from app.models.client import Client
from app.models.appointment import Appointment, AppointmentStatus
from app.models.recurrence_rule import RecurrenceRule
from app.models.therapist_client import TherapistClient
from app.schemas.appointment import (
    AppointmentCreate, AppointmentUpdate, AppointmentStatusUpdate,
    AppointmentResponse, RecurringAppointmentCreate,
)
from app.services import google_calendar
from app.services.email_service import send_appointment_confirmation, send_appointment_cancellation

router = APIRouter(tags=["appointments"])


def _build_response(appt: Appointment, db: Session) -> AppointmentResponse:
    rel = db.query(TherapistClient).filter(
        TherapistClient.therapist_id == appt.therapist_id,
        TherapistClient.client_id == appt.client_id,
    ).first()
    has_override = appt.override_price is not None and float(appt.override_price) != 0
    if has_override:
        effective_price = float(appt.override_price)
    elif rel and rel.default_session_price:
        effective_price = float(rel.default_session_price)
    elif appt.therapist and getattr(appt.therapist, "default_session_price", None):
        effective_price = float(appt.therapist.default_session_price)
    else:
        effective_price = None
    has_invoice = appt.billed

    return AppointmentResponse(
        id=appt.id,
        therapist_id=appt.therapist_id,
        client_id=appt.client_id,
        client_name=appt.client.name if appt.client else None,
        therapist_name=appt.therapist.name if appt.therapist else None,
        start_time=appt.start_time,
        end_time=appt.end_time,
        status=appt.status,
        session_type=appt.session_type,
        override_price=float(appt.override_price) if has_override else None,
        effective_price=effective_price,
        google_event_id=appt.google_event_id,
        completed_at=appt.completed_at,
        canceled_at=appt.canceled_at,
        session_notes=appt.session_notes,
        has_invoice=has_invoice,
        billed=appt.billed,
        recurrence_id=appt.recurrence_id,
        created_at=appt.created_at,
    )


# ─── Therapist endpoints ──────────────────────────────────────────────────────

@router.get("/therapist/availability")
def get_availability(
    date: str = Query(..., description="YYYY-MM-DD"),
    duration_minutes: int = Query(50),
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    if not therapist.google_calendar_connected:
        raise HTTPException(status_code=400, detail="Google Calendar not connected")
    slots = google_calendar.get_free_busy(therapist, db, date, duration_minutes)
    return {"date": date, "slots": slots}


@router.post("/therapist/appointments", response_model=AppointmentResponse, status_code=201)
def create_appointment(
    data: AppointmentCreate,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    rel = db.query(TherapistClient).filter(
        TherapistClient.therapist_id == therapist.id,
        TherapistClient.client_id == data.client_id,
        TherapistClient.is_active == True,
    ).first()
    if not rel:
        raise HTTPException(status_code=404, detail="Client not linked to this therapist")

    client = db.query(Client).filter(Client.id == data.client_id).first()

    appt = Appointment(
        therapist_id=therapist.id,
        client_id=data.client_id,
        start_time=data.start_time,
        end_time=data.end_time,
        session_type=data.session_type,
        override_price=data.override_price,
        session_notes=data.session_notes,
        status=AppointmentStatus.SCHEDULED,
        billed=False,
    )
    db.add(appt)
    db.flush()

    if therapist.google_calendar_connected:
        try:
            event = google_calendar.create_calendar_event(
                therapist=therapist, db=db,
                client_name=client.name, client_email=client.email,
                start_time=data.start_time, end_time=data.end_time,
                session_type=data.session_type, appointment_id=str(appt.id),
            )
            appt.google_event_id = event["id"]
            appt.google_calendar_id = therapist.google_calendar_id or "primary"
        except Exception:
            pass

    db.commit()
    db.refresh(appt)

    try:
        send_appointment_confirmation(
            client_email=client.email, client_name=client.name,
            therapist_name=therapist.name,
            start_time=data.start_time.strftime("%B %d, %Y at %I:%M %p"),
            end_time=data.end_time.strftime("%I:%M %p"),
            session_type=data.session_type,
        )
    except Exception:
        pass

    db.refresh(appt)
    appt.client = client
    appt.therapist = therapist
    return _build_response(appt, db)


@router.post("/therapist/appointments/recurring", response_model=List[AppointmentResponse], status_code=201)
def create_recurring_appointments(
    data: RecurringAppointmentCreate,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    rel = db.query(TherapistClient).filter(
        TherapistClient.therapist_id == therapist.id,
        TherapistClient.client_id == data.client_id,
        TherapistClient.is_active == True,
    ).first()
    if not rel:
        raise HTTPException(status_code=404, detail="Client not linked to this therapist")

    client = db.query(Client).filter(Client.id == data.client_id).first()

    # Save recurrence rule
    rule = RecurrenceRule(
        therapist_id=therapist.id,
        client_id=data.client_id,
        recurrence_type=data.recurrence_type,
        interval=1,
        start_date=data.start_date,
        end_date=data.end_date,
        occurrence_count=data.occurrence_count,
        session_type=data.session_type,
        override_price=data.override_price,
        duration_minutes=data.duration_minutes,
        start_hour=data.start_hour,
        start_minute=data.start_minute,
    )
    db.add(rule)
    db.flush()

    # Generate occurrence dates
    tz = ZoneInfo(therapist.timezone or "America/New_York")
    occurrence_dates = _generate_occurrences(
        recurrence_type=data.recurrence_type,
        start_date=data.start_date,
        end_date=data.end_date,
        occurrence_count=data.occurrence_count,
    )

    appointments = []
    for occ_date in occurrence_dates:
        start_local = datetime(occ_date.year, occ_date.month, occ_date.day,
                               data.start_hour, data.start_minute, tzinfo=tz)
        end_local = start_local + timedelta(minutes=data.duration_minutes)

        appt = Appointment(
            therapist_id=therapist.id,
            client_id=data.client_id,
            recurrence_id=rule.id,
            start_time=start_local,
            end_time=end_local,
            session_type=data.session_type,
            override_price=data.override_price,
            status=AppointmentStatus.SCHEDULED,
            billed=False,
        )
        db.add(appt)
        appointments.append(appt)

    db.flush()

    # Sync to Google Calendar
    if therapist.google_calendar_connected:
        for appt in appointments:
            try:
                event = google_calendar.create_calendar_event(
                    therapist=therapist, db=db,
                    client_name=client.name, client_email=client.email,
                    start_time=appt.start_time, end_time=appt.end_time,
                    session_type=data.session_type, appointment_id=str(appt.id),
                )
                appt.google_event_id = event["id"]
                appt.google_calendar_id = therapist.google_calendar_id or "primary"
            except Exception:
                pass

    db.commit()

    for appt in appointments:
        db.refresh(appt)
        appt.client = client
        appt.therapist = therapist

    return [_build_response(a, db) for a in appointments]


def _generate_occurrences(
    recurrence_type: str,
    start_date: date,
    end_date: Optional[date],
    occurrence_count: Optional[int],
) -> List[date]:
    dates = []
    current = start_date

    deltas = {
        "daily":    timedelta(days=1),
        "weekly":   timedelta(weeks=1),
        "biweekly": timedelta(weeks=2),
        "monthly":  None,  # special handling below
    }

    max_iter = occurrence_count or 104  # hard cap at 2 years

    while len(dates) < max_iter:
        if end_date and current > end_date:
            break
        dates.append(current)

        if recurrence_type == "monthly":
            # Advance one calendar month, keeping same day-of-month clamped to month end
            month = current.month + 1
            year = current.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            day = min(current.day, cal_mod.monthrange(year, month)[1])
            current = date(year, month, day)
        else:
            current = current + deltas[recurrence_type]

    return dates


@router.get("/therapist/appointments", response_model=List[AppointmentResponse])
def list_appointments(
    client_id: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    q = db.query(Appointment).options(
        joinedload(Appointment.client), joinedload(Appointment.therapist)
    ).filter(Appointment.therapist_id == therapist.id)

    if client_id:
        q = q.filter(Appointment.client_id == client_id)
    if status:
        q = q.filter(Appointment.status == status)
    if from_date:
        q = q.filter(Appointment.start_time >= from_date)
    if to_date:
        q = q.filter(Appointment.start_time <= to_date)

    appts = q.order_by(Appointment.start_time.desc()).all()
    return [_build_response(a, db) for a in appts]


@router.get("/therapist/appointments/{appointment_id}", response_model=AppointmentResponse)
def get_appointment(
    appointment_id: str,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    appt = _get_appt_for_therapist(db, appointment_id, therapist.id)
    return _build_response(appt, db)


@router.patch("/therapist/appointments/{appointment_id}", response_model=AppointmentResponse)
def update_appointment(
    appointment_id: str,
    data: AppointmentUpdate,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    appt = _get_appt_for_therapist(db, appointment_id, therapist.id)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(appt, field, value)

    if therapist.google_calendar_connected and appt.google_event_id and (
        data.start_time or data.end_time
    ):
        try:
            google_calendar.update_calendar_event(
                therapist=therapist, db=db,
                event_id=appt.google_event_id,
                start_time=appt.start_time,
                end_time=appt.end_time,
            )
        except Exception:
            pass

    db.commit()
    db.refresh(appt)
    return _build_response(appt, db)


@router.patch("/therapist/appointments/{appointment_id}/status", response_model=AppointmentResponse)
def update_appointment_status(
    appointment_id: str,
    data: AppointmentStatusUpdate,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    appt = _get_appt_for_therapist(db, appointment_id, therapist.id)
    # Completed → canceled only when no active invoice
    completed_transitions = [AppointmentStatus.CANCELED] if not appt.billed else []
    allowed_transitions = {
        AppointmentStatus.SCHEDULED: [AppointmentStatus.COMPLETED, AppointmentStatus.CANCELED, AppointmentStatus.NO_SHOW],
        AppointmentStatus.COMPLETED: completed_transitions,
        AppointmentStatus.CANCELED: [AppointmentStatus.COMPLETED],
        AppointmentStatus.NO_SHOW: [],
    }

    if data.status not in allowed_transitions.get(appt.status, []):
        if appt.status == AppointmentStatus.COMPLETED and appt.billed:
            raise HTTPException(status_code=400, detail="Cannot cancel a completed appointment with an active invoice. Void the invoice first.")
        raise HTTPException(status_code=400, detail=f"Cannot transition from {appt.status} to {data.status}")

    appt.status = data.status
    if data.status == AppointmentStatus.COMPLETED:
        appt.completed_at = datetime.utcnow()
        appt.canceled_at = None
        appt.cancellation_reason = None
    elif data.status == AppointmentStatus.CANCELED:
        appt.canceled_at = datetime.utcnow()
        appt.cancellation_reason = data.cancellation_reason

    if data.session_notes:
        appt.session_notes = data.session_notes

    if therapist.google_calendar_connected and appt.google_event_id:
        try:
            google_calendar.update_calendar_event(
                therapist=therapist, db=db,
                event_id=appt.google_event_id,
                status=data.status,
            )
        except Exception:
            pass

    if data.status == AppointmentStatus.CANCELED:
        try:
            send_appointment_cancellation(
                client_email=appt.client.email, client_name=appt.client.name,
                therapist_name=therapist.name,
                start_time=appt.start_time.strftime("%B %d, %Y at %I:%M %p"),
                reason=data.cancellation_reason,
            )
        except Exception:
            pass

    db.commit()
    db.refresh(appt)
    return _build_response(appt, db)


@router.delete("/therapist/appointments/{appointment_id}", status_code=204)
def cancel_and_delete_appointment(
    appointment_id: str,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    appt = _get_appt_for_therapist(db, appointment_id, therapist.id)
    if appt.status == AppointmentStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Cannot delete a completed appointment")

    if therapist.google_calendar_connected and appt.google_event_id:
        try:
            google_calendar.delete_calendar_event(therapist, db, appt.google_event_id)
        except Exception:
            pass

    appt.status = AppointmentStatus.CANCELED
    appt.canceled_at = datetime.utcnow()
    db.commit()


# ─── Client endpoints ─────────────────────────────────────────────────────────

@router.get("/client/appointments", response_model=List[AppointmentResponse])
def client_list_appointments(
    therapist_id: Optional[str] = None,
    status: Optional[str] = None,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    q = db.query(Appointment).options(
        joinedload(Appointment.client), joinedload(Appointment.therapist)
    ).filter(Appointment.client_id == client.id)

    if therapist_id:
        q = q.filter(Appointment.therapist_id == therapist_id)
    if status:
        q = q.filter(Appointment.status == status)

    appts = q.order_by(Appointment.start_time.desc()).all()
    return [_build_response(a, db) for a in appts]


@router.get("/client/appointments/{appointment_id}", response_model=AppointmentResponse)
def client_get_appointment(
    appointment_id: str,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    appt = db.query(Appointment).options(
        joinedload(Appointment.client), joinedload(Appointment.therapist)
    ).filter(
        Appointment.id == appointment_id,
        Appointment.client_id == client.id,
    ).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return _build_response(appt, db)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_appt_for_therapist(db: Session, appointment_id: str, therapist_id) -> Appointment:
    appt = db.query(Appointment).options(
        joinedload(Appointment.client), joinedload(Appointment.therapist)
    ).filter(
        Appointment.id == appointment_id,
        Appointment.therapist_id == therapist_id,
    ).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt
