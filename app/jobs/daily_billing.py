"""
Daily billing job — idempotent, retry-safe, frequency-aware.

Runs once per day. For each therapist-client pair, determines the billing
window based on the pair's billing_frequency, then queries:

    status = 'completed' AND billed = FALSE AND completed_at <= window_cutoff

Groups qualifying appointments into ONE aggregated invoice per pair per cycle.
Marks each appointment billed=True immediately to prevent double-billing.
"""
import calendar
import logging
from datetime import datetime, timedelta, date, time
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import distinct

from app.database import SessionLocal
from app.models.appointment import Appointment, AppointmentStatus
from app.models.invoice import Invoice, InvoiceStatus
from app.models.invoice_item import InvoiceItem
from app.models.therapist_client import TherapistClient, BillingFrequency
from app.models.therapist import Therapist
from app.models.client import Client
from app.services.stripe_service import generate_invoice_number
from app.services.email_service import send_invoice_email
from app.services.accounting.trigger import issue_accounting_invoice
from app.services.payment import get_payment_provider
from app.services.payment.base import PaymentProvider, PaymentSessionRequest
from app.models.payme_metadata import PayMePaymentMetadata
from app.services.exchange_rate import build_conversion_note
from app.config import settings

logger = logging.getLogger(__name__)

# Never look further back than this many days, regardless of billing frequency
CATCH_UP_DAYS = 90


def run_daily_billing(target_date: Optional[date] = None):
    """Entry point called by APScheduler and the admin trigger."""
    today = target_date or date.today()
    db = SessionLocal()
    try:
        logger.info(f"Daily billing: running for {today}")
        success, errors = 0, 0

        # Find every (therapist_id, client_id) pair that has unbilled completed appointments
        floor = datetime.combine(today - timedelta(days=CATCH_UP_DAYS), time.min)
        pairs = (
            db.query(distinct(Appointment.therapist_id), Appointment.client_id)
            .filter(
                Appointment.status == AppointmentStatus.COMPLETED,
                Appointment.billed == False,
                Appointment.start_time >= floor,
            )
            .all()
        )

        logger.info(f"Found {len(pairs)} therapist-client pairs with unbilled appointments")

        for therapist_id, client_id in pairs:
            try:
                created = _process_pair(db, therapist_id, client_id, today)
                if created:
                    success += 1
            except Exception as e:
                logger.error(f"Billing failed for pair ({therapist_id}, {client_id}): {e}",
                             exc_info=True)
                db.rollback()
                errors += 1

        logger.info(f"Daily billing complete: {success} invoices created, {errors} errors")
        return {"success": success, "errors": errors}
    finally:
        db.close()


def _process_pair(db: Session, therapist_id, client_id, today: date) -> bool:
    rel = db.query(TherapistClient).filter(
        TherapistClient.therapist_id == therapist_id,
        TherapistClient.client_id == client_id,
    ).first()
    if not rel:
        logger.debug(f"Pair ({therapist_id}, {client_id}): no TherapistClient record, skipping")
        return False

    cutoff = _billing_cutoff(rel.billing_frequency, rel.billing_anchor_day, today)
    if cutoff is None:
        logger.debug(
            f"Pair ({therapist_id}, {client_id}): not a billing day "
            f"(frequency={rel.billing_frequency}, anchor={rel.billing_anchor_day}, today={today})"
        )
        return False

    floor = datetime.combine(today - timedelta(days=CATCH_UP_DAYS), time.min)
    logger.debug(
        f"Pair ({therapist_id}, {client_id}): billing window {floor} → {cutoff} "
        f"(frequency={rel.billing_frequency})"
    )

    appointments = (
        db.query(Appointment)
        .filter(
            Appointment.therapist_id == therapist_id,
            Appointment.client_id == client_id,
            Appointment.status == AppointmentStatus.COMPLETED,
            Appointment.billed == False,
            Appointment.start_time >= floor,
            Appointment.start_time <= cutoff,
        )
        .order_by(Appointment.start_time)
        .all()
    )

    if not appointments:
        logger.info(
            f"Pair ({therapist_id}, {client_id}): no appointments in billing window "
            f"({floor.date()} → {cutoff.date()}) — nothing to bill"
        )
        return False

    # Mark billed immediately — prevents a concurrent run from double-billing
    for appt in appointments:
        appt.billed = True
    db.flush()

    therapist = db.query(Therapist).filter(Therapist.id == therapist_id).first()
    client = db.query(Client).filter(Client.id == client_id).first()

    # Resolve amounts — override → client default → therapist default → 0
    client_default = float(rel.default_session_price) if rel.default_session_price else None
    therapist_default = float(therapist.default_session_price) if (
        therapist and getattr(therapist, "default_session_price", None)
    ) else 0.0

    items_data = []
    total = 0.0
    for appt in appointments:
        if appt.override_price is not None and float(appt.override_price) != 0:
            amt = float(appt.override_price)
        elif client_default:
            amt = client_default
        else:
            amt = therapist_default
        total += amt
        items_data.append((appt, amt))

    currency = getattr(therapist, "default_currency", None) or "USD"
    due_date = datetime.utcnow() + timedelta(days=7)

    # Use appointment_id of the first (earliest) appointment for the invoice header
    first_appt = appointments[0]
    invoice = Invoice(
        therapist_id=therapist_id,
        client_id=client_id,
        appointment_id=first_appt.id if len(appointments) == 1 else None,
        invoice_number=generate_invoice_number(),
        amount=total,
        currency=currency,
        status=InvoiceStatus.UNPAID,
        due_date=due_date,
    )
    db.add(invoice)
    db.flush()

    for appt, amt in items_data:
        db.add(InvoiceItem(
            invoice_id=invoice.id,
            appointment_id=appt.id,
            amount=amt,
            description=f"Therapy Session — {appt.start_time.strftime('%B %d, %Y')}",
        ))

    # Payment session (provider-agnostic — invoice exists regardless)
    if therapist:
        _attach_payment_session(db, invoice, therapist)

    db.commit()
    db.refresh(invoice)

    # iCount tax invoice (Israeli therapists only)
    issue_accounting_invoice(invoice, therapist, db)

    # Email — always sent, with or without Stripe link
    try:
        session_date = first_appt.start_time.strftime("%B %d, %Y")
        if len(appointments) > 1:
            last = appointments[-1].start_time.strftime("%B %d, %Y")
            session_date = f"{session_date} – {last} ({len(appointments)} sessions)"
        other_currency = "ILS" if currency == "USD" else "USD"
        conversion_note = (
            build_conversion_note(total, currency, other_currency)
            if getattr(therapist, "show_conversion_note", False)
            else None
        )
        send_invoice_email(
            client_email=client.email,
            client_name=client.name,
            therapist_name=therapist.name,
            invoice_number=invoice.invoice_number,
            amount=total,
            due_date=due_date.strftime("%B %d, %Y"),
            payment_link=invoice.payment_link,
            session_date=session_date,
            payment_instructions=therapist.payment_instructions,
            currency=currency,
            conversion_note=conversion_note,
        )
    except Exception as e:
        logger.warning(f"Email failed for invoice {invoice.id}: {e}")

    logger.info(
        f"Invoice {invoice.invoice_number}: {len(appointments)} session(s), "
        f"{total:.2f} {currency} — {therapist.name} / {client.name}"
    )
    return True


def _attach_payment_session(db: Session, invoice: Invoice, therapist: Therapist):
    """Create a provider-specific payment session and store the result on the invoice."""
    provider_name = getattr(therapist, "payment_provider", None) or PaymentProvider.STRIPE
    invoice.payment_provider = provider_name
    try:
        provider = get_payment_provider(therapist)
        req = PaymentSessionRequest(
            invoice_id=str(invoice.id),
            therapist_id=str(therapist.id),
            client_id=str(invoice.client_id),
            amount=float(invoice.amount),
            currency=getattr(invoice, "currency", "USD"),
            invoice_number=invoice.invoice_number,
            success_url=f"{settings.FRONTEND_URL}/client/invoices?paid=true&invoice_id={invoice.id}",
            cancel_url=f"{settings.FRONTEND_URL}/client/invoices",
            description=f"Therapy Session — Invoice #{invoice.invoice_number}",
            metadata={
                "webhook_url": f"{settings.BACKEND_URL}/webhooks/payme"
                if provider_name == PaymentProvider.PAYME else ""
            },
        )
        session = provider.create_payment_session(req)
        if provider_name == PaymentProvider.PAYME:
            invoice.payme_sale_id = session.external_id
            invoice.payme_payment_link = session.payment_url
            db.add(PayMePaymentMetadata(
                payme_sale_id=session.external_id,
                invoice_id=invoice.id,
                therapist_id=therapist.id,
                client_id=invoice.client_id,
                extra_data={},
            ))
        else:
            invoice.stripe_checkout_session_id = session.external_id
            invoice.stripe_payment_link = session.payment_url
    except Exception as e:
        logger.warning(f"Payment session failed for invoice {invoice.id}: {e}")


def _billing_cutoff(
    billing_frequency: str,
    anchor_day: Optional[int],
    today: date,
) -> Optional[datetime]:
    """
    Return the latest datetime (inclusive) of completed_at that qualifies
    for billing today under the given frequency. Returns None if today is
    not a billing day for this frequency/anchor combination.
    """
    if billing_frequency == BillingFrequency.SAME_DAY:
        # Bill anything completed up to end of today
        return datetime.combine(today, time.max)

    if billing_frequency == BillingFrequency.NEXT_DAY:
        # Bill anything completed up to end of yesterday
        return datetime.combine(today - timedelta(days=1), time.max)

    if billing_frequency == BillingFrequency.WEEKLY:
        # anchor_day: 0=Mon … 6=Sun  (default Sunday = 6)
        anchor = anchor_day if anchor_day is not None else 6
        dow = today.weekday()  # 0=Mon
        if dow != anchor:
            return None  # not billing day
        # Bill everything completed before end of yesterday (the week just closed)
        return datetime.combine(today - timedelta(days=1), time.max)

    if billing_frequency == BillingFrequency.MONTHLY:
        # anchor_day: 1-28 (day of month, default 1st)
        anchor = anchor_day if anchor_day is not None else 1
        # Clamp to actual month length
        max_day = calendar.monthrange(today.year, today.month)[1]
        effective_anchor = min(anchor, max_day)
        if today.day != effective_anchor:
            return None  # not billing day
        # Bill everything completed before end of yesterday
        return datetime.combine(today - timedelta(days=1), time.max)

    # Unknown frequency — skip
    logger.warning(f"Unknown billing_frequency '{billing_frequency}', skipping")
    return None
