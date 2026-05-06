"""
Unified payment event handler.

Both /webhooks/stripe and /webhooks/payme parse their raw events,
normalize them into NormalizedEvent, then call handle_normalized_event().
Business logic lives here once — not in each webhook router.
"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment
from app.models.audit_log import AuditLog
from app.services.accounting.trigger import issue_accounting_receipt
from .base import NormalizedEvent

logger = logging.getLogger(__name__)


def handle_normalized_event(event: NormalizedEvent, db: Session) -> None:
    """
    Route a normalized event to the appropriate handler.
    All providers call this — never depends on provider-specific fields.
    """
    if event.event == "payment_succeeded":
        _handle_payment_succeeded(event, db)
    elif event.event == "payment_failed":
        _handle_payment_failed(event, db)
    elif event.event == "refund_issued":
        _handle_refund_issued(event, db)
    else:
        logger.debug(f"Unhandled normalized event type: {event.event}")


# ── Handlers ──────────────────────────────────────────────────────────────────

def _handle_payment_succeeded(event: NormalizedEvent, db: Session) -> None:
    invoice_id = event.metadata.get("invoice_id")
    if not invoice_id:
        logger.warning(f"payment_succeeded: no invoice_id in metadata (external={event.external_payment_id})")
        return

    invoice = _load_invoice(invoice_id, db)
    if not invoice:
        logger.warning(f"payment_succeeded: invoice {invoice_id} not found")
        return

    # Idempotency: already paid
    if invoice.status == InvoiceStatus.PAID:
        logger.info(f"Invoice {invoice_id} already paid — idempotent skip")
        return

    # Idempotency: payment record already exists for this external ID
    existing = db.query(Payment).filter(
        Payment.external_payment_id == event.external_payment_id
    ).first()
    if existing:
        logger.info(f"Payment {event.external_payment_id} already recorded — idempotent skip")
        return

    invoice.status  = InvoiceStatus.PAID
    invoice.paid_at = datetime.utcnow()

    db.add(Payment(
        invoice_id=invoice.id,
        provider=event.provider,
        external_payment_id=event.external_payment_id,
        amount=invoice.amount,
        status="succeeded",
        paid_at=datetime.utcnow(),
    ))

    db.add(AuditLog(
        therapist_id=invoice.therapist_id,
        action="payment_received",
        status="success",
        entity_type="invoice",
        entity_id=invoice.id,
        log_metadata={"provider": event.provider, "external_id": event.external_payment_id},
    ))

    db.commit()
    logger.info(f"Invoice {invoice_id} marked PAID via {event.provider} ({event.external_payment_id})")

    issue_accounting_receipt(invoice, db, payment_method="online")


def _handle_payment_failed(event: NormalizedEvent, db: Session) -> None:
    invoice_id = event.metadata.get("invoice_id")
    if not invoice_id:
        return

    # Idempotency
    existing = db.query(Payment).filter(
        Payment.external_payment_id == event.external_payment_id
    ).first()
    if existing:
        return

    invoice = _load_invoice(invoice_id, db)
    if not invoice:
        return

    db.add(Payment(
        invoice_id=invoice.id,
        provider=event.provider,
        external_payment_id=event.external_payment_id,
        amount=invoice.amount,
        status="failed",
        failure_reason=event.metadata.get("failure_reason"),
    ))

    db.add(AuditLog(
        therapist_id=invoice.therapist_id,
        action="payment_failed",
        status="failed",
        entity_type="invoice",
        entity_id=invoice.id,
        log_metadata={"provider": event.provider, "external_id": event.external_payment_id},
    ))

    db.commit()
    logger.warning(f"Payment failed for invoice {invoice_id} via {event.provider}")


def _handle_refund_issued(event: NormalizedEvent, db: Session) -> None:
    # Look up invoice via payment record
    payment = db.query(Payment).filter(
        Payment.external_payment_id == event.external_payment_id
    ).first()

    if not payment:
        logger.warning(f"refund_issued: no payment record for external_id {event.external_payment_id}")
        return

    invoice = _load_invoice(str(payment.invoice_id), db)
    if not invoice:
        return

    invoice.status = InvoiceStatus.REFUNDED
    db.add(AuditLog(
        therapist_id=invoice.therapist_id,
        action="payment_refunded",
        status="success",
        entity_type="invoice",
        entity_id=invoice.id,
        log_metadata={"provider": event.provider, "external_id": event.external_payment_id},
    ))
    db.commit()
    logger.info(f"Invoice {invoice.id} marked REFUNDED via {event.provider}")


# ── Helper ────────────────────────────────────────────────────────────────────

def _load_invoice(invoice_id: str, db: Session):
    return db.query(Invoice).options(
        joinedload(Invoice.client),
        joinedload(Invoice.therapist),
    ).filter(Invoice.id == invoice_id).first()
