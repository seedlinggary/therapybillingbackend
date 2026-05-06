"""
Stripe webhook handler — uses the unified payment event_handler for all
business logic so Stripe and PayMe behave identically after normalization.
"""
import logging
from fastapi import APIRouter, Request, HTTPException, Depends, Header
from sqlalchemy.orm import Session
import stripe

from app.database import get_db
from app.services.stripe_service import construct_webhook_event
from app.services.payment.stripe_provider import StripeProvider
from app.services.payment.event_handler import handle_normalized_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Events we care about — anything else is acknowledged and ignored
HANDLED_EVENTS = {
    "checkout.session.completed",
    "payment_intent.succeeded",
    "payment_intent.payment_failed",
    "charge.refunded",
}


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
    db: Session = Depends(get_db),
):
    payload = await request.body()

    try:
        raw_event = construct_webhook_event(payload, stripe_signature)
    except stripe.error.SignatureVerificationError as e:
        logger.warning(f"Stripe webhook signature verification failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = raw_event["type"]
    account_id = raw_event.get("account")
    logger.info(f"Stripe webhook: {event_type} (account={account_id or 'platform'})")

    if event_type not in HANDLED_EVENTS:
        return {"received": True}

    # For connected-account events Stripe only sends a thin object — re-fetch
    # from the connected account to get metadata and full payment details.
    obj = raw_event["data"]["object"]
    if account_id:
        obj = _refetch_connected(event_type, obj, account_id)
        if obj:
            raw_event["data"]["object"] = obj

    provider = StripeProvider(stripe_account_id=account_id)
    event = provider.normalize_event(raw_event)
    if not event:
        return {"received": True}

    handle_normalized_event(event, db)
    return {"received": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _refetch_connected(event_type: str, obj: dict, account_id: str):
    """Re-fetch the full object from a connected account so metadata is present."""
    try:
        if event_type == "checkout.session.completed":
            return stripe.checkout.Session.retrieve(obj["id"], stripe_account=account_id)
        if event_type in ("payment_intent.succeeded", "payment_intent.payment_failed"):
            return stripe.PaymentIntent.retrieve(obj["id"], stripe_account=account_id)
    except Exception as e:
        logger.warning(f"Could not re-fetch {event_type} object from connected account {account_id}: {e}")
    return obj
