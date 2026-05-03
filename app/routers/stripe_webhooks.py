"""
Stripe webhook handler — processes payment events from Stripe.
All events arrive on the therapist's connected account.
"""
import logging
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, Header
from sqlalchemy.orm import Session
import stripe

from app.database import get_db
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment
from app.services.stripe_service import construct_webhook_event
from app.services.accounting.trigger import issue_accounting_receipt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
    db: Session = Depends(get_db),
):
    payload = await request.body()

    try:
        event = construct_webhook_event(payload, stripe_signature)
    except stripe.error.SignatureVerificationError as e:
        logger.warning(f"Stripe webhook signature verification failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    # Connected account events include the account ID — objects must be retrieved
    # from that account rather than the platform.
    account_id = event.get("account")
    logger.info(f"Stripe webhook received: {event_type} (account={account_id or 'platform'})")

    if event_type == "checkout.session.completed":
        obj = event["data"]["object"]
        if account_id:
            try:
                obj = stripe.checkout.Session.retrieve(
                    obj["id"], stripe_account=account_id
                )
            except Exception as e:
                logger.warning(f"Could not retrieve session from connected account: {e}")
        _handle_checkout_completed(obj, db)

    elif event_type == "payment_intent.succeeded":
        obj = event["data"]["object"]
        if account_id:
            try:
                obj = stripe.PaymentIntent.retrieve(
                    obj["id"], stripe_account=account_id
                )
            except Exception as e:
                logger.warning(f"Could not retrieve payment intent from connected account: {e}")
        _handle_payment_intent_succeeded(obj, db)

    elif event_type == "payment_intent.payment_failed":
        _handle_payment_intent_failed(event["data"]["object"], db)

    elif event_type == "charge.refunded":
        _handle_charge_refunded(event["data"]["object"], db)

    return {"received": True}


def _handle_checkout_completed(session: dict, db: Session):
    invoice_id = session.get("metadata", {}).get("invoice_id")
    if not invoice_id:
        return

    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        logger.warning(f"Checkout completed but invoice {invoice_id} not found")
        return

    if invoice.status == InvoiceStatus.PAID:
        logger.info(f"Invoice {invoice_id} already paid, idempotent skip")
        return

    payment_intent_id = session.get("payment_intent")

    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = datetime.utcnow()
    invoice.stripe_payment_intent_id = payment_intent_id

    payment = Payment(
        invoice_id=invoice.id,
        amount=invoice.amount,
        stripe_payment_intent_id=payment_intent_id or session["id"],
        status="succeeded",
        paid_at=datetime.utcnow(),
    )
    db.add(payment)
    db.commit()
    logger.info(f"Invoice {invoice_id} marked as PAID via checkout session {session['id']}")
    _issue_accounting_receipt(invoice, db)


def _handle_payment_intent_succeeded(pi: dict, db: Session):
    invoice_id = pi.get("metadata", {}).get("invoice_id")
    if not invoice_id:
        return

    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice or invoice.status == InvoiceStatus.PAID:
        return

    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = datetime.utcnow()
    invoice.stripe_payment_intent_id = pi["id"]

    existing_payment = db.query(Payment).filter(Payment.stripe_payment_intent_id == pi["id"]).first()
    if not existing_payment:
        db.add(Payment(
            invoice_id=invoice.id,
            amount=invoice.amount,
            stripe_payment_intent_id=pi["id"],
            status="succeeded",
            paid_at=datetime.utcnow(),
        ))

    db.commit()
    logger.info(f"Invoice {invoice_id} marked as PAID via payment_intent {pi['id']}")
    _issue_accounting_receipt(invoice, db)


def _handle_payment_intent_failed(pi: dict, db: Session):
    invoice_id = pi.get("metadata", {}).get("invoice_id")
    if not invoice_id:
        return

    existing = db.query(Payment).filter(Payment.stripe_payment_intent_id == pi["id"]).first()
    if not existing:
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if invoice:
            db.add(Payment(
                invoice_id=invoice.id,
                amount=invoice.amount,
                stripe_payment_intent_id=pi["id"],
                status="failed",
                failure_reason=pi.get("last_payment_error", {}).get("message"),
            ))
            db.commit()
    logger.warning(f"Payment failed for invoice {invoice_id}, intent {pi['id']}")


def _handle_charge_refunded(charge: dict, db: Session):
    pi_id = charge.get("payment_intent")
    if not pi_id:
        return

    invoice = db.query(Invoice).filter(Invoice.stripe_payment_intent_id == pi_id).first()
    if invoice:
        invoice.status = InvoiceStatus.REFUNDED
        db.commit()
        logger.info(f"Invoice {invoice.id} marked as REFUNDED")


def _issue_accounting_receipt(invoice: Invoice, db: Session):
    issue_accounting_receipt(invoice, db, payment_method="online")
