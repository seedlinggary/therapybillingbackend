"""
Shared invoice creation helper — used by the same_day auto-billing trigger
in the appointments router and can be reused anywhere else that needs to
bill a single completed appointment.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.invoice import Invoice, InvoiceStatus
from app.models.invoice_item import InvoiceItem
from app.models.appointment import Appointment
from app.models.therapist import Therapist
from app.models.therapist_client import TherapistClient
from app.models.payme_metadata import PayMePaymentMetadata
from app.services.stripe_service import generate_invoice_number
from app.services.email_service import send_invoice_email
from app.services.accounting.trigger import issue_accounting_invoice
from app.services.payment import get_payment_provider
from app.services.payment.base import PaymentProvider, PaymentSessionRequest
from app.services.exchange_rate import build_conversion_note
from app.config import settings

logger = logging.getLogger(__name__)


def create_appointment_invoice(
    db: Session,
    appt: Appointment,
    therapist: Therapist,
    rel: TherapistClient = None,
) -> Invoice:
    """
    Create and send an invoice for a single completed appointment.
    Sets appt.billed = True and commits. Returns the Invoice.
    """
    if rel is None:
        rel = db.query(TherapistClient).filter(
            TherapistClient.therapist_id == therapist.id,
            TherapistClient.client_id == appt.client_id,
        ).first()

    if appt.override_price is not None and float(appt.override_price) != 0:
        amount = float(appt.override_price)
    elif rel and rel.default_session_price:
        amount = float(rel.default_session_price)
    elif getattr(therapist, "default_session_price", None):
        amount = float(therapist.default_session_price)
    else:
        amount = 0.0

    currency = getattr(therapist, "default_currency", None) or "USD"
    due_date = datetime.utcnow() + timedelta(days=7)

    invoice = Invoice(
        therapist_id=therapist.id,
        client_id=appt.client_id,
        appointment_id=appt.id,
        invoice_number=generate_invoice_number(),
        amount=amount,
        currency=currency,
        status=InvoiceStatus.UNPAID,
        due_date=due_date,
    )
    db.add(invoice)
    db.flush()

    db.add(InvoiceItem(
        invoice_id=invoice.id,
        appointment_id=appt.id,
        amount=amount,
        description=f"{appt.session_type or 'Session'} — {appt.start_time.strftime('%B %d, %Y')}",
    ))

    _attach_payment_session(db, invoice, therapist)

    appt.billed = True
    db.commit()
    db.refresh(invoice)

    issue_accounting_invoice(invoice, therapist, db)

    if getattr(rel, 'notify_invoice', True):
        try:
            other_currency = "ILS" if currency == "USD" else "USD"
            conversion_note = (
                build_conversion_note(amount, currency, other_currency)
                if getattr(therapist, "show_conversion_note", False)
                else None
            )
            send_invoice_email(
                client_email=appt.client.email,
                client_name=appt.client.name,
                therapist_name=therapist.name,
                invoice_number=invoice.invoice_number,
                amount=amount,
                due_date=due_date.strftime("%B %d, %Y"),
                payment_link=invoice.payment_link,
                session_date=appt.start_time.strftime("%B %d, %Y"),
                payment_instructions=therapist.payment_instructions,
                currency=currency,
                conversion_note=conversion_note,
            )
        except Exception as e:
            logger.warning(f"Email failed for auto-billed invoice {invoice.id}: {e}")

    return invoice


def _attach_payment_session(db: Session, invoice: Invoice, therapist: Therapist):
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
            description=f"Invoice #{invoice.invoice_number}",
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
        elif provider_name == PaymentProvider.PAYPAL:
            invoice.paypal_order_id = session.external_id
            invoice.paypal_payment_link = session.payment_url
        else:
            invoice.stripe_checkout_session_id = session.external_id
            invoice.stripe_payment_link = session.payment_url
    except Exception as e:
        logger.warning(f"Payment session failed for invoice {invoice.id}: {e}")
