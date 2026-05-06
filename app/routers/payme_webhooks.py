"""
PayMe webhook handler.

PayMe does not support arbitrary metadata on payments, so this handler:
1. Looks up the payme_sale_id in payme_payment_metadata to find the invoice.
2. Verifies the HMAC-SHA256 signature using the therapist's API key.
3. Normalizes the event and delegates to the shared event_handler.
"""
import json
import logging
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.therapist import Therapist
from app.models.payme_metadata import PayMePaymentMetadata
from app.services.payment.payme_provider import PayMeProvider
from app.services.payment.event_handler import handle_normalized_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/payme")
async def payme_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await request.body()
    headers = dict(request.headers)

    try:
        raw_event = json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    payme_sale_id = raw_event.get("payme_sale_id")
    if not payme_sale_id:
        logger.warning("PayMe webhook: missing payme_sale_id")
        raise HTTPException(status_code=400, detail="Missing payme_sale_id")

    # Resolve invoice from our metadata table (PayMe carries no metadata)
    meta = db.query(PayMePaymentMetadata).filter(
        PayMePaymentMetadata.payme_sale_id == payme_sale_id
    ).first()

    if not meta:
        # Unknown sale — may be a test ping or a race condition.  Return 200 so
        # PayMe does not retry indefinitely.
        logger.warning(f"PayMe webhook: unknown payme_sale_id {payme_sale_id}")
        return {"received": True}

    therapist = db.query(Therapist).filter(Therapist.id == meta.therapist_id).first()
    if not therapist:
        return {"received": True}

    seller_id = getattr(therapist, "payme_seller_id", None)
    api_key   = getattr(therapist, "payme_api_key", None)

    # Verify signature when credentials are present
    if seller_id and api_key:
        provider = PayMeProvider(seller_payme_id=seller_id, api_key=api_key)
        if not provider.verify_webhook(payload, headers):
            logger.warning(f"PayMe webhook: bad signature for sale {payme_sale_id}")
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        logger.warning(f"PayMe webhook: therapist {therapist.id} has no PayMe credentials — skipping signature check")
        provider = PayMeProvider(seller_payme_id="", api_key="")

    # Inject resolved metadata so normalize_event can populate NormalizedEvent.metadata
    raw_event["_resolved_metadata"] = {
        "invoice_id":   str(meta.invoice_id),
        "therapist_id": str(meta.therapist_id),
        "client_id":    str(meta.client_id),
        **(meta.extra_data or {}),
    }

    event = provider.normalize_event(raw_event)
    if not event:
        logger.info(f"PayMe webhook: unhandled sale_status '{raw_event.get('sale_status')}' for sale {payme_sale_id}")
        return {"received": True}

    logger.info(f"PayMe webhook: {event.event} — sale {payme_sale_id}")
    handle_normalized_event(event, db)
    return {"received": True}
