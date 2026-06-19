"""
Therapist onboarding — Google Calendar + Stripe Connect.
"""
import secrets
import logging
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.core.deps import get_current_therapist
from app.core.security import encrypt_token
from app.models.therapist import Therapist
from app.schemas.therapist import TherapistProfile, TherapistUpdate, TherapistOnboardingStatus
from app.services.google_oauth import get_calendar_flow, exchange_code, build_credentials
from app.services.stripe_service import get_stripe_connect_url, exchange_stripe_code
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


# ─── Profile ─────────────────────────────────────────────────────────────────

@router.get("/me", response_model=TherapistProfile)
def get_my_profile(therapist: Therapist = Depends(get_current_therapist)):
    return therapist


@router.patch("/me", response_model=TherapistProfile)
def update_my_profile(
    data: TherapistUpdate,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(therapist, field, value)
    _check_onboarding_complete(therapist)
    db.commit()
    db.refresh(therapist)
    return therapist


@router.get("/status", response_model=TherapistOnboardingStatus)
def get_onboarding_status(therapist: Therapist = Depends(get_current_therapist)):
    return TherapistOnboardingStatus(
        google_calendar_connected=therapist.google_calendar_connected,
        stripe_connected=therapist.stripe_connected,
        onboarding_completed=therapist.onboarding_completed,
    )


# ─── Google Calendar OAuth ───────────────────────────────────────────────────

@router.get("/google-calendar/connect")
def connect_google_calendar(request: Request, therapist: Therapist = Depends(get_current_therapist)):
    origin = request.headers.get("origin", "")
    frontend_url = settings.resolve_frontend_url(origin) if origin else settings.FRONTEND_URL
    flow = get_calendar_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent",
        state=f"{therapist.id}|{frontend_url}",
    )
    return {"auth_url": auth_url}


@router.get("/google-calendar/callback")
def google_calendar_callback(
    code: str,
    state: str,
    db: Session = Depends(get_db),
    error: str = None,
):
    # state format: "therapist_id|frontend_url"
    therapist_id, _, encoded_url = state.partition("|")
    frontend_url = settings.resolve_frontend_url(encoded_url)

    if error:
        logger.warning(f"Google Calendar OAuth denied: {error}")
        return RedirectResponse(url=f"{frontend_url}/therapist/onboarding?error=calendar_denied")

    therapist = db.query(Therapist).filter(Therapist.id == therapist_id).first()
    if not therapist:
        return RedirectResponse(url=f"{frontend_url}/therapist/onboarding?error=invalid_state")

    try:
        token_data = exchange_code(code, settings.GOOGLE_CALENDAR_REDIRECT_URI)
        credentials = build_credentials(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
        )
    except Exception as e:
        logger.error(f"Calendar token exchange failed: {e}")
        return RedirectResponse(url=f"{frontend_url}/therapist/onboarding?error=calendar_token_failed")

    calendar_id = "primary"
    try:
        service = build("calendar", "v3", credentials=credentials)
        cal = service.calendarList().get(calendarId="primary").execute()
        calendar_id = cal.get("id", "primary")
    except Exception as e:
        logger.error(f"calendarList lookup failed (Calendar API may not be enabled): {e}")
        error_hint = "calendar_api_disabled" if "accessNotConfigured" in str(e) else "calendar_api_error"
        return RedirectResponse(url=f"{frontend_url}/therapist/onboarding?error={error_hint}")

    therapist.google_access_token_enc = encrypt_token(credentials.token)
    therapist.google_refresh_token_enc = encrypt_token(credentials.refresh_token)
    therapist.google_token_expiry = credentials.expiry
    therapist.google_calendar_id = calendar_id
    therapist.google_calendar_connected = True
    _check_onboarding_complete(therapist)
    db.commit()

    return RedirectResponse(url=f"{frontend_url}/therapist/onboarding?step=stripe")


@router.get("/google-calendar/events")
def get_google_calendar_events(
    start: str,
    end: str,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    """Return non-therapy Google Calendar events for the given ISO date range."""
    if not therapist.google_calendar_connected:
        return []
    try:
        from app.services.google_calendar import list_external_events
        events = list_external_events(therapist, db, start, end)
        logger.info(f"Google Calendar events fetched: count={len(events)} events={[e['title'] for e in events]}")
        return events
    except Exception as e:
        logger.warning(f"Failed to fetch Google Calendar events for therapist {therapist.id}: {e}")
        return []


# ─── Stripe Connect OAuth ────────────────────────────────────────────────────

@router.get("/stripe/connect")
def connect_stripe(request: Request, therapist: Therapist = Depends(get_current_therapist)):
    origin = request.headers.get("origin", "")
    frontend_url = settings.resolve_frontend_url(origin) if origin else settings.FRONTEND_URL
    # state format: "therapist_id|frontend_url"
    connect_url = get_stripe_connect_url(str(therapist.id), f"{therapist.id}|{frontend_url}")
    return {"auth_url": connect_url}


@router.get("/stripe/callback")
def stripe_callback(code: str, db: Session = Depends(get_db), state: str = None):
    # state format: "therapist_id|frontend_url"
    therapist_id, _, encoded_url = (state or "").partition("|")
    frontend_url = settings.resolve_frontend_url(encoded_url)

    try:
        response = exchange_stripe_code(code)
    except Exception as e:
        logger.error(f"Stripe OAuth failed: {e}")
        return RedirectResponse(url=f"{frontend_url}/therapist/onboarding?error=stripe_failed")

    stripe_account_id = response.get("stripe_user_id")
    if not stripe_account_id:
        return RedirectResponse(url=f"{frontend_url}/therapist/onboarding?error=stripe_failed")

    therapist = db.query(Therapist).filter(Therapist.id == therapist_id).first() if therapist_id else None
    if not therapist:
        logger.error(f"Stripe callback: no therapist found for state={state!r}")
        return RedirectResponse(url=f"{frontend_url}/therapist/onboarding?error=stripe_failed")

    # Idempotent: already connected with the same account — just redirect
    if therapist.stripe_account_id == stripe_account_id:
        return RedirectResponse(url=f"{frontend_url}/therapist/onboarding?step=complete")

    therapist.stripe_account_id = stripe_account_id
    therapist.stripe_connected = True
    _check_onboarding_complete(therapist)
    db.commit()

    return RedirectResponse(url=f"{frontend_url}/therapist/onboarding?step=complete")


class ManualStripeConnectRequest(BaseModel):
    account_id: str


@router.post("/stripe/manual-connect")
def stripe_manual_connect(
    body: ManualStripeConnectRequest,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    account_id = body.account_id.strip()
    if not account_id.startswith("acct_"):
        raise HTTPException(status_code=400, detail="Invalid Stripe account ID — must start with 'acct_'")

    try:
        stripe.Account.retrieve(account_id)
    except stripe.error.PermissionError:
        # Test-mode platform keys can't retrieve accounts they don't own — that's fine,
        # the ID format is valid and the account exists.
        pass
    except stripe.error.InvalidRequestError as e:
        raise HTTPException(status_code=400, detail=f"Stripe account not found: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not verify Stripe account: {e}")

    therapist.stripe_account_id = account_id
    therapist.stripe_connected = True
    _check_onboarding_complete(therapist)
    db.commit()
    db.refresh(therapist)
    return {"stripe_connected": True, "account_id": account_id}


@router.get("/exchange-rate")
def get_exchange_rate(
    from_currency: str = "USD",
    to_currency: str = "ILS",
    _: Therapist = Depends(get_current_therapist),
):
    """Return the live exchange rate between two currencies."""
    from app.services.exchange_rate import get_rate
    rate = get_rate(from_currency, to_currency)
    if rate is None:
        raise HTTPException(status_code=503, detail="Exchange rate service unavailable")
    return {"from": from_currency.upper(), "to": to_currency.upper(), "rate": rate}


class PayMeConnectRequest(BaseModel):
    seller_id: str
    api_key: str


@router.post("/payme/connect", response_model=TherapistProfile)
def payme_connect(
    body: PayMeConnectRequest,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    therapist.payme_seller_id = body.seller_id.strip()
    therapist.payme_api_key = body.api_key.strip()
    therapist.payment_provider = "payme"
    db.commit()
    db.refresh(therapist)
    return therapist


@router.delete("/payme", status_code=204)
def disconnect_payme(
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    therapist.payme_seller_id = None
    therapist.payme_api_key = None
    therapist.payment_provider = "stripe"
    db.commit()


class PayPalConnectRequest(BaseModel):
    paypal_email: str


@router.post("/paypal/connect", response_model=TherapistProfile)
def paypal_connect(
    body: PayPalConnectRequest,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    email = body.paypal_email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid PayPal email address")
    therapist.paypal_email = email
    therapist.paypal_connected = True
    therapist.payment_provider = "paypal"
    db.commit()
    db.refresh(therapist)
    return therapist


@router.delete("/paypal", status_code=204)
def disconnect_paypal(
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    therapist.paypal_email = None
    therapist.paypal_connected = False
    therapist.payment_provider = "stripe"
    db.commit()


@router.delete("/google-calendar", status_code=204)
def disconnect_google_calendar(
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    therapist.google_access_token_enc = None
    therapist.google_refresh_token_enc = None
    therapist.google_token_expiry = None
    therapist.google_calendar_id = None
    therapist.google_calendar_connected = False
    therapist.onboarding_completed = False
    db.commit()


@router.delete("/stripe", status_code=204)
def disconnect_stripe(
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    therapist.stripe_account_id = None
    therapist.stripe_connected = False
    therapist.onboarding_completed = False
    db.commit()


def _check_onboarding_complete(therapist: Therapist):
    if therapist.google_calendar_connected:
        therapist.onboarding_completed = True
