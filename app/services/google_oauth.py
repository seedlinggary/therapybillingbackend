import logging
import httpx
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from app.config import settings

logger = logging.getLogger(__name__)

THERAPIST_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

def _client_config(redirect_uri: str) -> dict:
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def get_google_auth_flow(redirect_uri: str, scopes: list) -> Flow:
    flow = Flow.from_client_config(_client_config(redirect_uri), scopes=scopes, redirect_uri=redirect_uri)
    return flow


def get_therapist_login_flow() -> Flow:
    return get_google_auth_flow(settings.GOOGLE_REDIRECT_URI, THERAPIST_SCOPES)


def get_calendar_flow() -> Flow:
    return get_google_auth_flow(settings.GOOGLE_CALENDAR_REDIRECT_URI, CALENDAR_SCOPES)


def exchange_code(code: str, redirect_uri: str) -> dict:
    """
    Exchange an authorization code for tokens via a direct HTTP POST.

    Using httpx directly instead of recreating the oauthlib Flow avoids the
    state-mismatch problem that occurs when the Flow object in the callback
    differs from the one that generated the auth URL.
    """
    with httpx.Client(timeout=10) as client:
        response = client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if response.status_code != 200:
        detail = response.json()
        error = detail.get("error_description") or detail.get("error") or "unknown"
        logger.error(f"Google token exchange failed ({response.status_code}): {error}")
        raise ValueError(f"Token exchange failed: {error}")

    return response.json()


def get_user_info(access_token: str) -> dict:
    """Fetch Google user profile using an access token."""
    with httpx.Client(timeout=10) as client:
        response = client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if response.status_code != 200:
        raise ValueError(f"Failed to fetch user info: {response.status_code}")

    return response.json()


def get_google_user_info(credentials: Credentials) -> dict:
    """Legacy helper — accepts Credentials object (used by calendar flow)."""
    service = build("oauth2", "v2", credentials=credentials)
    return service.userinfo().get().execute()


def build_credentials(access_token: str, refresh_token: str, expiry=None) -> Credentials:
    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        expiry=expiry,
    )


def refresh_credentials_if_needed(creds: Credentials) -> Credentials:
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds
