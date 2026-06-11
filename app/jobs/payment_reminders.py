"""
Payment reminder job — runs daily at 03:00 UTC.

For each therapist with reminder_frequency_days > 0, checks whether enough
days have passed since the last batch was sent. If so, groups all unpaid
invoices by client and sends one email per client listing everything they owe.
Invoices created within the last 24h are excluded (they just got an initial email).

reminder_repeat=True  (default): keeps sending every X days until paid.
reminder_repeat=False: sends each invoice's reminder exactly once.
Per-client notify_reminder=False skips that client entirely.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.invoice import Invoice, InvoiceStatus
from app.models.therapist import Therapist
from app.models.client import Client
from app.models.therapist_client import TherapistClient
from app.services.email_service import send_payment_reminder

logger = logging.getLogger(__name__)


def run_payment_reminders():
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        sent, skipped, errors = 0, 0, 0

        therapists = (
            db.query(Therapist)
            .filter(
                Therapist.reminder_frequency_days > 0,
                Therapist.is_active == True,
            )
            .all()
        )

        for therapist in therapists:
            freq = therapist.reminder_frequency_days
            repeat = getattr(therapist, 'reminder_repeat', True)

            if repeat:
                last = therapist.last_payment_reminder_at
                if last is not None:
                    days_since = (now - last).days
                    if days_since < freq:
                        skipped += 1
                        continue

            try:
                emails_sent = _send_reminders_for_therapist(db, therapist, now)
                if repeat:
                    therapist.last_payment_reminder_at = now
                    db.commit()
                sent += emails_sent
                logger.info(f"Reminders sent for {therapist.name}: {emails_sent} client(s)")
            except Exception as e:
                logger.error(f"Reminder batch failed for therapist {therapist.id}: {e}", exc_info=True)
                db.rollback()
                errors += 1

        logger.info(f"Payment reminders complete: {sent} emails sent, {skipped} therapists skipped, {errors} errors")
        return {"sent": sent, "skipped": skipped, "errors": errors}
    finally:
        db.close()


def _send_reminders_for_therapist(db: Session, therapist: Therapist, now: datetime) -> int:
    cutoff = now - timedelta(hours=24)
    repeat = getattr(therapist, 'reminder_repeat', True)

    base_q = (
        db.query(Invoice)
        .filter(
            Invoice.therapist_id == therapist.id,
            Invoice.status == InvoiceStatus.UNPAID,
            Invoice.created_at <= cutoff,
        )
    )

    if not repeat:
        base_q = base_q.filter(Invoice.reminder_sent_at.is_(None))

    unpaid = base_q.order_by(Invoice.client_id, Invoice.created_at).all()

    if not unpaid:
        return 0

    by_client: dict = {}
    for inv in unpaid:
        key = str(inv.client_id)
        by_client.setdefault(key, []).append(inv)

    currency = getattr(therapist, "default_currency", None) or "USD"
    emails_sent = 0

    for client_id, invoices in by_client.items():
        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            continue

        rel = db.query(TherapistClient).filter(
            TherapistClient.therapist_id == therapist.id,
            TherapistClient.client_id == client_id,
        ).first()
        if rel and not getattr(rel, 'notify_reminder', True):
            continue

        invoice_data = [
            {
                "invoice_number": inv.invoice_number,
                "amount": float(inv.amount),
                "due_date": inv.due_date.strftime("%B %d, %Y"),
                "payment_link": inv.payment_link,
            }
            for inv in invoices
        ]

        try:
            send_payment_reminder(
                client_email=client.email,
                client_name=client.name,
                therapist_name=therapist.name,
                invoices=invoice_data,
                payment_instructions=therapist.payment_instructions,
                currency=currency,
            )
            for inv in invoices:
                inv.reminder_sent_at = now
            db.flush()
            emails_sent += 1
        except Exception as e:
            logger.warning(f"Failed to send reminder to {client.email}: {e}")

    return emails_sent
