import stripe
from datetime import datetime, timedelta
from app.config import settings
from app.models.therapist import Therapist
from app.models.invoice import Invoice
import uuid

stripe.api_key = settings.STRIPE_SECRET_KEY
stripe.client_id = settings.STRIPE_CLIENT_ID


def get_stripe_connect_url(therapist_id: str, state: str) -> str:
    """Generate Stripe Connect OAuth URL for a therapist."""
    return stripe.OAuth.authorize_url(
        scope="read_write",
        redirect_uri=settings.STRIPE_CONNECT_REDIRECT_URI,
        state=state,
    )


def exchange_stripe_code(code: str) -> dict:
    """Exchange OAuth code for Stripe account credentials."""
    return stripe.OAuth.token(grant_type="authorization_code", code=code)


def create_checkout_session(
    invoice: Invoice,
    therapist: Therapist,
    success_url: str,
    cancel_url: str,
) -> dict:
    """Create a Stripe Checkout Session on the therapist's connected account."""
    if not therapist.stripe_account_id:
        raise ValueError("Therapist has not connected Stripe")

    amount_cents = int(float(invoice.amount) * 100)
    currency = (getattr(invoice, "currency", None) or "USD").lower()

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": currency,
                "product_data": {
                    "name": f"Therapy Session - Invoice #{invoice.invoice_number}",
                    "description": f"Session on {invoice.appointment.start_time.strftime('%B %d, %Y') if invoice.appointment else ''}",
                },
                "unit_amount": amount_cents,
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "invoice_id": str(invoice.id),
            "therapist_id": str(invoice.therapist_id),
            "client_id": str(invoice.client_id),
            "appointment_id": str(invoice.appointment_id),
        },
        stripe_account=therapist.stripe_account_id,
        payment_intent_data={
            "metadata": {
                "invoice_id": str(invoice.id),
                "therapist_id": str(invoice.therapist_id),
                "client_id": str(invoice.client_id),
            },
            "transfer_data": None,  # direct charge to connected account
        },
    )

    return session


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    return stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)


def generate_invoice_number() -> str:
    now = datetime.utcnow()
    return f"INV-{now.strftime('%Y%m')}-{str(uuid.uuid4())[:8].upper()}"
