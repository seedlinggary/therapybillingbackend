"""
Returns the correct payment provider for a given therapist.
"""
from app.models.therapist import Therapist
from .base import BasePaymentProvider, PaymentProvider
from .stripe_provider import StripeProvider
from .payme_provider import PayMeProvider
from .paypal_provider import PayPalProvider


def get_payment_provider(therapist: Therapist) -> BasePaymentProvider:
    provider = getattr(therapist, "payment_provider", None) or PaymentProvider.STRIPE

    if provider == PaymentProvider.PAYME:
        seller_id = getattr(therapist, "payme_seller_id", None)
        api_key   = getattr(therapist, "payme_api_key", None)
        if not seller_id or not api_key:
            raise ValueError("PayMe credentials not configured for this therapist")
        return PayMeProvider(seller_payme_id=seller_id, api_key=api_key)

    if provider == PaymentProvider.PAYPAL:
        paypal_email = getattr(therapist, "paypal_email", None)
        if not paypal_email:
            raise ValueError("Therapist has not connected PayPal")
        return PayPalProvider(therapist_paypal_email=paypal_email)

    # Default: Stripe
    return StripeProvider(stripe_account_id=getattr(therapist, "stripe_account_id", None))
