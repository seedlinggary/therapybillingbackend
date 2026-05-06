"""
Provider-agnostic payment abstraction.

All payment providers implement BasePaymentProvider and map their
internal states into the unified PaymentStatus lifecycle.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any


class PaymentStatus:
    PENDING           = "pending"
    REQUIRES_ACTION   = "requires_action"
    PAID              = "paid"
    FAILED            = "failed"
    REFUNDED          = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class PaymentProvider:
    STRIPE = "stripe"
    PAYME  = "payme"


@dataclass
class PaymentSessionRequest:
    invoice_id:     str
    therapist_id:   str
    client_id:      str
    amount:         float
    currency:       str
    invoice_number: str
    success_url:    str
    cancel_url:     str
    description:    str = ""
    metadata:       dict = field(default_factory=dict)


@dataclass
class PaymentSession:
    """Returned by create_payment_session — provider-neutral."""
    provider:    str
    external_id: str    # Stripe checkout session ID or PayMe sale ID
    payment_url: str    # URL to redirect client to
    status:      str = PaymentStatus.PENDING


@dataclass
class NormalizedEvent:
    """
    Provider-neutral webhook event.
    Both Stripe and PayMe map their raw events into this format
    before any business logic is applied.
    """
    event:               str    # payment_succeeded | payment_failed | refund_issued
    provider:            str    # stripe | payme
    external_payment_id: str
    amount:              float
    currency:            str
    metadata:            dict = field(default_factory=dict)


@dataclass
class RefundResult:
    success:            bool
    external_refund_id: Optional[str] = None
    error:              Optional[str] = None


class BasePaymentProvider(ABC):

    @abstractmethod
    def create_payment_session(self, data: PaymentSessionRequest) -> PaymentSession:
        """Create a checkout/payment session and return a redirect URL."""

    @abstractmethod
    def retrieve_payment(self, payment_id: str) -> dict:
        """Fetch current state of a payment from the provider."""

    @abstractmethod
    def refund_payment(self, payment_id: str, amount: Optional[float] = None) -> RefundResult:
        """Issue a full or partial refund."""

    @abstractmethod
    def verify_webhook(self, payload: bytes, headers: dict) -> bool:
        """Verify the webhook signature/authenticity."""

    @abstractmethod
    def parse_webhook_event(self, payload: bytes, headers: dict) -> Any:
        """Parse raw bytes into a provider-specific event object."""

    @abstractmethod
    def normalize_event(self, raw_event: Any) -> Optional[NormalizedEvent]:
        """Convert a provider-specific event into a NormalizedEvent, or None if unhandled."""
