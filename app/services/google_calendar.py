from datetime import datetime, timedelta
from typing import Optional, List
from googleapiclient.discovery import build
from app.services.google_oauth import build_credentials, refresh_credentials_if_needed
from app.core.security import decrypt_token, encrypt_token
from app.models.therapist import Therapist
from sqlalchemy.orm import Session
import pytz


def get_calendar_service(therapist: Therapist, db: Session):
    if not therapist.google_calendar_connected:
        raise ValueError("Therapist has not connected Google Calendar")

    access_token = decrypt_token(therapist.google_access_token_enc)
    refresh_token = decrypt_token(therapist.google_refresh_token_enc)

    creds = build_credentials(access_token, refresh_token, therapist.google_token_expiry)
    creds = refresh_credentials_if_needed(creds)

    # Persist refreshed tokens if they changed
    if creds.token != access_token:
        therapist.google_access_token_enc = encrypt_token(creds.token)
        therapist.google_token_expiry = creds.expiry
        db.add(therapist)
        db.commit()

    return build("calendar", "v3", credentials=creds)


def get_free_busy(therapist: Therapist, db: Session, date_str: str, duration_minutes: int = 50) -> List[dict]:
    """Return available slots for a given date in therapist's timezone."""
    tz = pytz.timezone(therapist.timezone)
    day = datetime.strptime(date_str, "%Y-%m-%d")
    start_of_day = tz.localize(day.replace(hour=8, minute=0))
    end_of_day = tz.localize(day.replace(hour=20, minute=0))

    service = get_calendar_service(therapist, db)
    calendar_id = therapist.google_calendar_id or "primary"

    freebusy = service.freebusy().query(body={
        "timeMin": start_of_day.isoformat(),
        "timeMax": end_of_day.isoformat(),
        "timeZone": therapist.timezone,
        "items": [{"id": calendar_id}],
    }).execute()

    busy_periods = freebusy["calendars"][calendar_id]["busy"]
    busy = [(
        datetime.fromisoformat(b["start"]),
        datetime.fromisoformat(b["end"])
    ) for b in busy_periods]

    # Generate 30-min slot candidates from 8am-8pm
    slots = []
    slot_start = start_of_day
    while slot_start + timedelta(minutes=duration_minutes) <= end_of_day:
        slot_end = slot_start + timedelta(minutes=duration_minutes)
        if not any(b_start < slot_end and b_end > slot_start for b_start, b_end in busy):
            slots.append({
                "start": slot_start.isoformat(),
                "end": slot_end.isoformat(),
            })
        slot_start += timedelta(minutes=30)

    return slots


def create_calendar_event(
    therapist: Therapist,
    db: Session,
    client_name: str,
    client_email: str,
    start_time: datetime,
    end_time: datetime,
    session_type: str = "Individual",
    appointment_id: str = None,
) -> dict:
    service = get_calendar_service(therapist, db)
    calendar_id = therapist.google_calendar_id or "primary"

    event = {
        "summary": f"Therapy - {client_name} ({session_type})",
        "description": f"Session ID: {appointment_id}",
        "start": {"dateTime": start_time.isoformat(), "timeZone": therapist.timezone},
        "end": {"dateTime": end_time.isoformat(), "timeZone": therapist.timezone},
        "attendees": [{"email": client_email}],
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 1440},  # 24h
                {"method": "popup", "minutes": 30},
            ],
        },
    }

    # sendUpdates="none" — the app's own email handles client notifications.
    # "all" would spam clients with a separate Google invite per recurring session.
    return service.events().insert(calendarId=calendar_id, body=event, sendUpdates="none").execute()


def update_calendar_event(
    therapist: Therapist,
    db: Session,
    event_id: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    status: Optional[str] = None,
) -> dict:
    service = get_calendar_service(therapist, db)
    calendar_id = therapist.google_calendar_id or "primary"

    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    if start_time:
        event["start"] = {"dateTime": start_time.isoformat(), "timeZone": therapist.timezone}
    if end_time:
        event["end"] = {"dateTime": end_time.isoformat(), "timeZone": therapist.timezone}
    if status == "canceled":
        event["status"] = "cancelled"

    return service.events().update(calendarId=calendar_id, eventId=event_id, body=event, sendUpdates="all").execute()


def delete_calendar_event(therapist: Therapist, db: Session, event_id: str):
    service = get_calendar_service(therapist, db)
    calendar_id = therapist.google_calendar_id or "primary"
    service.events().delete(calendarId=calendar_id, eventId=event_id, sendUpdates="all").execute()
