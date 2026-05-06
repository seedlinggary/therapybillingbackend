"""
Admin router — superuser can read/update any therapist or client.
All endpoints require role=admin in the JWT.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_admin
from app.models.admin_user import AdminUser
from app.models.therapist import Therapist
from app.models.client import Client
from app.models.therapist_client import TherapistClient
from app.models.appointment import Appointment
from app.models.invoice import Invoice

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ── Therapists ────────────────────────────────────────────────────────────────

@router.get("/therapists")
def list_therapists(
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    rows = db.query(Therapist).order_by(Therapist.name).all()
    return [_therapist_summary(t) for t in rows]


@router.get("/therapists/{therapist_id}")
def get_therapist(
    therapist_id: str,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    t = _get_therapist_or_404(therapist_id, db)
    return _therapist_detail(t)


class TherapistPatch(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    license_number: Optional[str] = None
    bio: Optional[str] = None
    payment_instructions: Optional[str] = None
    country: Optional[str] = None
    default_currency: Optional[str] = None
    ils_exchange_rate: Optional[float] = None
    default_session_price: Optional[float] = None
    default_billing_frequency: Optional[str] = None
    default_billing_anchor_day: Optional[int] = None
    payment_provider: Optional[str] = None
    payme_seller_id: Optional[str] = None
    is_active: Optional[bool] = None


@router.patch("/therapists/{therapist_id}")
def update_therapist(
    therapist_id: str,
    data: TherapistPatch,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    t = _get_therapist_or_404(therapist_id, db)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(t, field, value)
    db.commit()
    db.refresh(t)
    return _therapist_detail(t)


@router.get("/therapists/{therapist_id}/clients")
def get_therapist_clients(
    therapist_id: str,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    _get_therapist_or_404(therapist_id, db)
    rows = db.query(TherapistClient).filter(TherapistClient.therapist_id == therapist_id).all()
    return [
        {
            "id": str(r.id),
            "client_id": str(r.client_id),
            "name": r.client.name if r.client else "—",
            "email": r.client.email if r.client else "—",
            "is_active": r.is_active,
            "default_session_price": float(r.default_session_price or 0),
            "billing_frequency": r.billing_frequency,
        }
        for r in rows
    ]


@router.get("/therapists/{therapist_id}/invoices")
def get_therapist_invoices(
    therapist_id: str,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    _get_therapist_or_404(therapist_id, db)
    rows = (
        db.query(Invoice)
        .filter(Invoice.therapist_id == therapist_id)
        .order_by(Invoice.created_at.desc())
        .limit(200)
        .all()
    )
    return [_invoice_summary(inv) for inv in rows]


@router.get("/therapists/{therapist_id}/appointments")
def get_therapist_appointments(
    therapist_id: str,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    _get_therapist_or_404(therapist_id, db)
    rows = (
        db.query(Appointment)
        .filter(Appointment.therapist_id == therapist_id)
        .order_by(Appointment.start_time.desc())
        .limit(200)
        .all()
    )
    return [_appointment_summary(a) for a in rows]


# ── Clients ───────────────────────────────────────────────────────────────────

@router.get("/clients")
def list_clients(
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    rows = db.query(Client).order_by(Client.name).all()
    return [_client_summary(c) for c in rows]


@router.get("/clients/{client_id}")
def get_client(
    client_id: str,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    c = _get_client_or_404(client_id, db)
    return _client_detail(c)


class ClientPatch(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None
    timezone: Optional[str] = None


@router.patch("/clients/{client_id}")
def update_client(
    client_id: str,
    data: ClientPatch,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    c = _get_client_or_404(client_id, db)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(c, field, value)
    db.commit()
    db.refresh(c)
    return _client_detail(c)


@router.get("/clients/{client_id}/invoices")
def get_client_invoices(
    client_id: str,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    _get_client_or_404(client_id, db)
    rows = (
        db.query(Invoice)
        .filter(Invoice.client_id == client_id)
        .order_by(Invoice.created_at.desc())
        .limit(200)
        .all()
    )
    return [_invoice_summary(inv) for inv in rows]


@router.get("/clients/{client_id}/appointments")
def get_client_appointments(
    client_id: str,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    _get_client_or_404(client_id, db)
    rows = (
        db.query(Appointment)
        .filter(Appointment.client_id == client_id)
        .order_by(Appointment.start_time.desc())
        .limit(200)
        .all()
    )
    return [_appointment_summary(a) for a in rows]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_therapist_or_404(therapist_id: str, db: Session) -> Therapist:
    t = db.query(Therapist).filter(Therapist.id == therapist_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Therapist not found")
    return t


def _get_client_or_404(client_id: str, db: Session) -> Client:
    c = db.query(Client).filter(Client.id == client_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    return c


def _therapist_summary(t: Therapist) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "email": t.email,
        "country": t.country,
        "default_currency": t.default_currency,
        "payment_provider": t.payment_provider,
        "stripe_connected": t.stripe_connected,
        "google_calendar_connected": t.google_calendar_connected,
        "onboarding_completed": t.onboarding_completed,
        "is_active": t.is_active,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _therapist_detail(t: Therapist) -> dict:
    d = _therapist_summary(t)
    d.update({
        "phone": t.phone,
        "license_number": t.license_number,
        "bio": t.bio,
        "timezone": t.timezone,
        "payment_instructions": t.payment_instructions,
        "ils_exchange_rate": float(t.ils_exchange_rate) if t.ils_exchange_rate else None,
        "default_session_price": float(t.default_session_price) if t.default_session_price else None,
        "default_billing_frequency": t.default_billing_frequency,
        "default_billing_anchor_day": t.default_billing_anchor_day,
        "payme_seller_id": t.payme_seller_id,
        "stripe_account_id": t.stripe_account_id,
        "picture_url": t.picture_url,
    })
    return d


def _client_summary(c: Client) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "email": c.email,
        "phone": c.phone,
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _client_detail(c: Client) -> dict:
    d = _client_summary(c)
    d.update({
        "timezone": c.timezone,
        "notes": c.notes,
        "address": c.address,
        "email_verified": c.email_verified,
    })
    return d


def _invoice_summary(inv: Invoice) -> dict:
    return {
        "id": str(inv.id),
        "invoice_number": inv.invoice_number,
        "client_id": str(inv.client_id),
        "client_name": inv.client.name if inv.client else "—",
        "therapist_id": str(inv.therapist_id),
        "amount": float(inv.amount),
        "currency": inv.currency,
        "status": inv.status,
        "payment_provider": getattr(inv, "payment_provider", "stripe"),
        "payment_link": inv.payment_link if hasattr(inv, "payment_link") else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }


def _appointment_summary(a: Appointment) -> dict:
    return {
        "id": str(a.id),
        "client_id": str(a.client_id),
        "client_name": a.client.name if a.client else "—",
        "therapist_id": str(a.therapist_id),
        "start_time": a.start_time.isoformat() if a.start_time else None,
        "end_time": a.end_time.isoformat() if a.end_time else None,
        "status": a.status,
        "session_type": a.session_type,
        "billed": a.billed,
        "override_price": float(a.override_price) if a.override_price else None,
    }
