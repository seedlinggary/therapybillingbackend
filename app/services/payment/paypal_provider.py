"""
PayPal payment provider.

Uses PayPal Orders v2 API with platform credentials.  The therapist's
PayPal Business email is set as the `payee` on each purchase unit, so
payments route directly to them (requires PayPal Marketplace/Partner setup
in production).

Venmo support is automatic — PayPal's hosted checkout page (the `approve`
link) surfaces Venmo as a funding option for eligible buyers.

Webhook flow:
  1. CHECKOUT.ORDER.APPROVED  → we capture the order
  2. PAYMENT.CAPTURE.COMPLETED → we mark the invoice paid
"""
from __future__ import annotations
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


class PayPalProvider(BasePaymentProvider):
    def __init__(self, therapist_paypal_email: str):
        self.therapist_paypal_email = therapist_paypal_email
        self.base_url = settings.PAYPAL_BASE_URL

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _access_token(self) -> str:
        if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
            raise ValueError("PayPal credentials are not configured")
        r = httpx.post(
            f"{self.base_url}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
            timeout=15,
        )
        r.raise_for_status()
        return r.json()["access_token"]

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
        }

    # ── Session creation ──────────────────────────────────────────────────────

    def create_payment_session(self, data: PaymentSessionRequest) -> PaymentSession:
        if not self.therapist_paypal_email:
            raise ValueError("Therapist has not connected PayPal")

        body: dict = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "custom_id": data.invoice_id,
                "reference_id": data.invoice_number,
                "description": data.description or f"Invoice #{data.invoice_number}",
                "amount": {
                    "currency_code": data.currency.upper(),
                    "value": f"{data.amount:.2f}",
                },
                "payee": {
                    "email_address": self.therapist_paypal_email,
                },
            }],
            "application_context": {
                "return_url": data.success_url,
                "cancel_url": data.cancel_url,
                "brand_name": "TherapyBilling",
                "landing_page": "LOGIN",
                "shipping_preference": "NO_SHIPPING",
                "user_action": "PAY_NOW",
            },
        }

        r = httpx.post(
            f"{self.base_url}/v2/checkout/orders",
            json=body,
            headers=self._headers(),
            timeout=15,
        )
        r.raise_for_status()
        order = r.json()

        order_id = order["id"]
        approve_url = next(
            (link["href"] for link in order.get("links", []) if link["rel"] == "approve"),
            None,
        )
        if not approve_url:
            raise ValueError("PayPal did not return an approve link")

        return PaymentSession(
            provider=PaymentProvider.PAYPAL,
            external_id=order_id,
            payment_url=approve_url,
            status=PaymentStatus.PENDING,
        )

    # ── Capture ───────────────────────────────────────────────────────────────

    def capture_order(self, order_id: str) -> dict:
        """Capture an approved PayPal order.  Called from the webhook handler."""
        r = httpx.post(
            f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
            json={},
            headers=self._headers(),
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    # ── Retrieval + refund ────────────────────────────────────────────────────

    def retrieve_payment(self, payment_id: str) -> dict:
        r = httpx.get(
            f"{self.base_url}/v2/checkout/orders/{payment_id}",
            headers=self._headers(),
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def refund_payment(self, payment_id: str, amount: Optional[float] = None) -> RefundResult:
        body: dict = {}
        if amount is not None:
            body["amount"] = {"value": f"{amount:.2f}", "currency_code": "USD"}
        try:
            r = httpx.post(
                f"{self.base_url}/v2/payments/captures/{payment_id}/refund",
                json=body,
                headers=self._headers(),
                timeout=15,
            )
            r.raise_for_status()
            return RefundResult(success=True, external_refund_id=r.json().get("id"))
        except Exception as exc:
            return RefundResult(success=False, error=str(exc))

    # ── Webhooks ──────────────────────────────────────────────────────────────

    def verify_webhook(self, payload: bytes, headers: dict) -> bool:
        transmission_id   = headers.get("paypal-transmission-id")
        transmission_time = headers.get("paypal-transmission-time")
        cert_url          = headers.get("paypal-cert-url")
        actual_sig        = headers.get("paypal-transmission-sig")
        auth_algo         = headers.get("paypal-auth-algo", "SHA256withRSA")

        if not all([transmission_id, transmission_time, cert_url, actual_sig]):
            logger.warning("PayPal webhook: missing signature headers")
            return False

        if not settings.PAYPAL_WEBHOOK_ID:
            logger.warning("PAYPAL_WEBHOOK_ID not set — skipping signature verification")
            return True

        try:
            token = self._access_token()
            resp = httpx.post(
                f"{self.base_url}/v1/notifications/verify-webhook-signature",
                json={
                    "auth_algo": auth_algo,
                    "cert_url": cert_url,
                    "transmission_id": transmission_id,
                    "transmission_sig": actual_sig,
                    "transmission_time": transmission_time,
                    "webhook_id": settings.PAYPAL_WEBHOOK_ID,
                    "webhook_event": json.loads(payload),
                },
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=10,
            )
            return resp.json().get("verification_status") == "SUCCESS"
        except Exception as exc:
            logger.error(f"PayPal webhook verification error: {exc}")
            return False

    def parse_webhook_event(self, payload: bytes, headers: dict) -> Any:
        return json.loads(payload)

    def normalize_event(self, raw_event: Any) -> Optional[NormalizedEvent]:
        event_type = raw_event.get("event_type", "")
        resource   = raw_event.get("resource", {})

        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            invoice_id = raw_event.get("_resolved_invoice_id")
            amount     = float(resource.get("amount", {}).get("value", 0))
            currency   = resource.get("amount", {}).get("currency_code", "USD").upper()
            return NormalizedEvent(
                event="payment_succeeded",
                provider=PaymentProvider.PAYPAL,
                external_payment_id=resource.get("id", ""),
                amount=amount,
                currency=currency,
                metadata={"invoice_id": invoice_id} if invoice_id else {},
            )

        if event_type == "PAYMENT.CAPTURE.DENIED":
            invoice_id = raw_event.get("_resolved_invoice_id")
            return NormalizedEvent(
                event="payment_failed",
                provider=PaymentProvider.PAYPAL,
                external_payment_id=resource.get("id", ""),
                amount=float(resource.get("amount", {}).get("value", 0)),
                currency=resource.get("amount", {}).get("currency_code", "USD").upper(),
                metadata={"invoice_id": invoice_id} if invoice_id else {},
            )

        if event_type == "PAYMENT.CAPTURE.REFUNDED":
            invoice_id = raw_event.get("_resolved_invoice_id")
            return NormalizedEvent(
                event="refund_issued",
                provider=PaymentProvider.PAYPAL,
                external_payment_id=resource.get("id", ""),
                amount=float(resource.get("amount", {}).get("value", 0)),
                currency=resource.get("amount", {}).get("currency_code", "USD").upper(),
                metadata={"invoice_id": invoice_id} if invoice_id else {},
            )

        return None
