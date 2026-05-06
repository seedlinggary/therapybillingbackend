"""
PayMe payment provider (payme.co.il).

PayMe is an Israeli payment aggregator supporting credit cards, Bit, Apple Pay.
Amounts are in agorot (1 ILS = 100 agorot) for ILS, or cents for other currencies.

Webhook verification: HMAC-SHA256 over the raw request body, signed with the
seller's API key, delivered in the X-Payme-Signature header.

PayMe does not support arbitrary metadata on payments. We store the
invoice_id → payme_sale_id mapping in `payme_payment_metadata` (DB) and inject
it into the event before normalization.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
from typing import Optional, Any

import httpx

from app.config import settings
from .base import (
    BasePaymentProvider, PaymentSession, PaymentSessionRequest,
    NormalizedEvent, RefundResult, PaymentStatus, PaymentProvider,
)

logger = logging.getLogger(__name__)

PAYME_API_BASE = getattr(settings, "PAYME_API_BASE_URL", "https://ng.payme.co.il/api/v2")


class PayMeProvider(BasePaymentProvider):
    def __init__(self, seller_payme_id: str, api_key: str):
        self.seller_payme_id = seller_payme_id
        self.api_key = api_key

    def _headers(self) -> dict:
        return {
            "seller-payme-id": self.seller_payme_id,
            "Content-Type": "application/json",
        }

    # ── Session creation ──────────────────────────────────────────────────────

    def create_payment_session(self, data: PaymentSessionRequest) -> PaymentSession:
        # PayMe uses integer minor units (agorot for ILS, cents for USD)
        amount_minor = int(data.amount * 100)

        payload = {
            "sale_price":            amount_minor,
            "currency":              data.currency,
            "product_name":          data.description or f"Invoice #{data.invoice_number}",
            "sale_callback_url":     data.metadata.get("webhook_url", ""),
            "sale_return_url":       data.success_url,
            "sale_cancel_url":       data.cancel_url,
            "sale_payment_methods":  ["credit_card", "bit"],
            "sale_send_notification": True,
            "language":              "he" if data.currency == "ILS" else "en",
        }

        response = httpx.post(
            f"{PAYME_API_BASE}/sales/generate",
            json=payload,
            headers=self._headers(),
            timeout=15,
        )
        response.raise_for_status()
        result = response.json()

        if result.get("status_code") != "success":
            raise ValueError(f"PayMe sale creation failed: {result.get('status_description', result)}")

        return PaymentSession(
            provider=PaymentProvider.PAYME,
            external_id=result["payme_sale_id"],
            payment_url=result["sale_url"],
            status=PaymentStatus.PENDING,
        )

    # ── Retrieval + refund ────────────────────────────────────────────────────

    def retrieve_payment(self, payment_id: str) -> dict:
        response = httpx.post(
            f"{PAYME_API_BASE}/sales/get-sales",
            json={"payme_sale_id": payment_id},
            headers=self._headers(),
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    def refund_payment(self, payment_id: str, amount: Optional[float] = None) -> RefundResult:
        try:
            payload: dict = {"payme_sale_id": payment_id}
            if amount is not None:
                payload["refund_amount"] = int(amount * 100)

            response = httpx.post(
                f"{PAYME_API_BASE}/sales/refund",
                json=payload,
                headers=self._headers(),
                timeout=15,
            )
            response.raise_for_status()
            result = response.json()

            if result.get("status_code") == "success":
                return RefundResult(success=True, external_refund_id=payment_id)
            return RefundResult(success=False, error=result.get("status_description"))
        except Exception as e:
            logger.error(f"PayMe refund failed for {payment_id}: {e}")
            return RefundResult(success=False, error=str(e))

    # ── Webhooks ──────────────────────────────────────────────────────────────

    def verify_webhook(self, payload: bytes, headers: dict) -> bool:
        received = (
            headers.get("x-payme-signature")
            or headers.get("X-Payme-Signature")
        )
        if not received:
            logger.warning("PayMe webhook: missing X-Payme-Signature header")
            return False
        expected = hmac.new(
            self.api_key.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, received)

    def parse_webhook_event(self, payload: bytes, headers: dict) -> Any:
        return json.loads(payload)

    def normalize_event(self, raw_event: Any) -> Optional[NormalizedEvent]:
        """
        `raw_event` must have `_resolved_metadata` injected by the webhook
        handler before this is called (since PayMe carries no metadata).
        """
        sale_status   = raw_event.get("sale_status")
        payme_sale_id = raw_event.get("payme_sale_id", "")
        price         = raw_event.get("price_total", {})
        amount        = price.get("amount", 0) / 100
        currency      = price.get("currency", "ILS")
        metadata      = raw_event.get("_resolved_metadata", {})

        if sale_status == "success":
            return NormalizedEvent(
                event="payment_succeeded",
                provider=PaymentProvider.PAYME,
                external_payment_id=payme_sale_id,
                amount=amount,
                currency=currency,
                metadata=metadata,
            )

        if sale_status in ("failed", "error"):
            return NormalizedEvent(
                event="payment_failed",
                provider=PaymentProvider.PAYME,
                external_payment_id=payme_sale_id,
                amount=amount,
                currency=currency,
                metadata=metadata,
            )

        if sale_status == "refund":
            return NormalizedEvent(
                event="refund_issued",
                provider=PaymentProvider.PAYME,
                external_payment_id=payme_sale_id,
                amount=amount,
                currency=currency,
                metadata=metadata,
            )

        return None
