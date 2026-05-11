"""
PayPal webhook handler.

Handles two event types:
  - CHECKOUT.ORDER.APPROVED  → captures the PayPal order
  - PAYMENT.CAPTURE.COMPLETED / DENIED / REFUNDED → normalized into the
    shared event_handler pipeline using DB lookup (paypal_order_id) to
    resolve the invoice, similar to how the PayMe handler works.
"""
import json
import logging
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.invoice import Invoice
from app.models.therapist import Therapist
from app.services.payment.paypal_provider import PayPalProvider
from app.services.payment.event_handler import handle_normalized_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/paypal")
async def paypal_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    try:
        raw_event = json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = raw_event.get("event_type", "")
    resource   = raw_event.get("resource", {})

    # ── Signature verification (uses a dummy email — only needs platform creds) ──
    provider = PayPalProvider(therapist_paypal_email="")
    if not provider.verify_webhook(payload, headers):
        logger.warning(f"PayPal webhook: invalid signature for event {event_type}")
        raise HTTPException(status_code=400, detail="Invalid PayPal webhook signature")

    logger.info(f"PayPal webhook received: {event_type}")

    # ── CHECKOUT.ORDER.APPROVED → capture the order ───────────────────────────
    if event_type == "CHECKOUT.ORDER.APPROVED":
        order_id = resource.get("id")
        if not order_id:
            return {"received": True}

        invoice = db.query(Invoice).filter(Invoice.paypal_order_id == order_id).first()
        if not invoice:
            logger.warning(f"PayPal: APPROVED event for unknown order {order_id}")
            return {"received": True}

        therapist = db.query(Therapist).filter(Therapist.id == invoice.therapist_id).first()
        paypal_email = getattr(therapist, "paypal_email", "") if therapist else ""

        try:
            capture_provider = PayPalProvider(therapist_paypal_email=paypal_email)
            capture_provider.capture_order(order_id)
            logger.info(f"PayPal: captured order {order_id} for invoice {invoice.id}")
        except Exception as exc:
            logger.error(f"PayPal: failed to capture order {order_id}: {exc}")

        return {"received": True}

    # ── PAYMENT.CAPTURE.* → resolve invoice, normalize, delegate ─────────────
    if event_type in ("PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.REFUNDED"):
        # PayPal includes the order_id in supplementary_data on capture events
        order_id = (
            resource.get("supplementary_data", {})
                    .get("related_ids", {})
                    .get("order_id")
        )
        invoice = None
        if order_id:
            invoice = db.query(Invoice).filter(Invoice.paypal_order_id == order_id).first()

        if not invoice:
            # Fallback: try custom_id stored directly on the capture resource
            custom_id = resource.get("custom_id")
            if custom_id:
                invoice = db.query(Invoice).filter(Invoice.id == custom_id).first()

        if not invoice:
            logger.warning(
                f"PayPal: {event_type} — cannot resolve invoice "
                f"(order_id={order_id})"
            )
            return {"received": True}

        # Inject the resolved invoice_id so normalize_event can populate metadata
        raw_event["_resolved_invoice_id"] = str(invoice.id)

        event = provider.normalize_event(raw_event)
        if not event:
            return {"received": True}

        logger.info(f"PayPal: {event.event} — order {order_id}, invoice {invoice.id}")
        handle_normalized_event(event, db)

    return {"received": True}
