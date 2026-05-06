"""
Stripe payment provider — wraps the existing Stripe SDK calls.
"""
from __future__ import annotations
import logging
from typing import Optional, Any

import stripe

from app.config import settings
from .base import (
    BasePaymentProvider, PaymentSession, PaymentSessionRequest,
    NormalizedEvent, RefundResult, PaymentStatus, PaymentProvider,
)

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeProvider(BasePaymentProvider):
    def __init__(self, stripe_account_id: Optional[str] = None):
        self.stripe_account_id = stripe_account_id

    # ── Session creation ──────────────────────────────────────────────────────

    def create_payment_session(self, data: PaymentSessionRequest) -> PaymentSession:
        if not self.stripe_account_id:
            raise ValueError("Therapist has not connected Stripe")

        amount_cents = int(data.amount * 100)

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": data.currency.lower(),
                    "product_data": {"name": data.description or f"Invoice #{data.invoice_number}"},
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=data.success_url,
            cancel_url=data.cancel_url,
            metadata={
                "invoice_id":    data.invoice_id,
                "therapist_id":  data.therapist_id,
                "client_id":     data.client_id,
                **data.metadata,
            },
            stripe_account=self.stripe_account_id,
            payment_intent_data={
                "metadata": {
                    "invoice_id":   data.invoice_id,
                    "therapist_id": data.therapist_id,
                    "client_id":    data.client_id,
                },
            },
        )

        return PaymentSession(
            provider=PaymentProvider.STRIPE,
            external_id=session["id"],
            payment_url=session["url"],
            status=PaymentStatus.PENDING,
        )

    # ── Retrieval + refund ────────────────────────────────────────────────────

    def retrieve_payment(self, payment_id: str) -> dict:
        kwargs = {}
        if self.stripe_account_id:
            kwargs["stripe_account"] = self.stripe_account_id
        return dict(stripe.PaymentIntent.retrieve(payment_id, **kwargs))

    def refund_payment(self, payment_id: str, amount: Optional[float] = None) -> RefundResult:
        try:
            kwargs: dict = {"payment_intent": payment_id}
            if amount is not None:
                kwargs["amount"] = int(amount * 100)
            if self.stripe_account_id:
                kwargs["stripe_account"] = self.stripe_account_id
            refund = stripe.Refund.create(**kwargs)
            return RefundResult(success=True, external_refund_id=refund["id"])
        except stripe.error.StripeError as e:
            return RefundResult(success=False, error=str(e))

    # ── Webhooks ──────────────────────────────────────────────────────────────

    def verify_webhook(self, payload: bytes, headers: dict) -> bool:
        sig = headers.get("stripe-signature") or headers.get("Stripe-Signature")
        try:
            stripe.Webhook.construct_event(payload, sig, settings.STRIPE_WEBHOOK_SECRET)
            return True
        except Exception:
            return False

    def parse_webhook_event(self, payload: bytes, headers: dict) -> Any:
        sig = headers.get("stripe-signature") or headers.get("Stripe-Signature")
        return stripe.Webhook.construct_event(payload, sig, settings.STRIPE_WEBHOOK_SECRET)

    def normalize_event(self, raw_event: Any) -> Optional[NormalizedEvent]:
        event_type = raw_event["type"]
        obj        = raw_event["data"]["object"]

        if event_type == "checkout.session.completed":
            meta = obj.get("metadata") or {}
            return NormalizedEvent(
                event="payment_succeeded",
                provider=PaymentProvider.STRIPE,
                external_payment_id=obj["id"],
                amount=obj.get("amount_total", 0) / 100,
                currency=(obj.get("currency") or "usd").upper(),
                metadata=meta,
            )

        if event_type == "payment_intent.succeeded":
            meta = obj.get("metadata") or {}
            return NormalizedEvent(
                event="payment_succeeded",
                provider=PaymentProvider.STRIPE,
                external_payment_id=obj["id"],
                amount=obj.get("amount", 0) / 100,
                currency=(obj.get("currency") or "usd").upper(),
                metadata=meta,
            )

        if event_type == "payment_intent.payment_failed":
            meta = obj.get("metadata") or {}
            return NormalizedEvent(
                event="payment_failed",
                provider=PaymentProvider.STRIPE,
                external_payment_id=obj["id"],
                amount=obj.get("amount", 0) / 100,
                currency=(obj.get("currency") or "usd").upper(),
                metadata=meta,
            )

        if event_type == "charge.refunded":
            return NormalizedEvent(
                event="refund_issued",
                provider=PaymentProvider.STRIPE,
                external_payment_id=obj.get("payment_intent") or obj["id"],
                amount=obj.get("amount_refunded", 0) / 100,
                currency=(obj.get("currency") or "usd").upper(),
                metadata={},
            )

        return None
