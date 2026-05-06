"""
Auth router — Google OAuth for therapists, JWT for clients.
"""
import random
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.core.security import (
    create_access_token, create_refresh_token,
    hash_password, verify_password, decode_token
)
from app.models.therapist import Therapist
from app.models.client import Client
from app.models.admin_user import AdminUser
from app.schemas.client import ClientLogin, ClientRegister, ActivateAccount, TokenResponse, ForgotPassword, ResetPassword
from app.services.google_oauth import get_therapist_login_flow, exchange_code, get_user_info
from app.services.email_service import send_password_reset_email

router = APIRouter(prefix="/auth", tags=["auth"])


# ─── Therapist: Google OAuth ──────────────────────────────────────────────────

@router.get("/google/login")
def google_login():
    flow = get_therapist_login_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account",
    )
    return {"auth_url": auth_url}


@router.get("/google/callback")
def google_callback(
    code: str,
    db: Session = Depends(get_db),
    state: str = None,   # Google always sends state; accept it to avoid 422
    error: str = None,   # Google sends error= on denial
):
    if error:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error={error}")

    try:
        token_data = exchange_code(code, settings.GOOGLE_REDIRECT_URI)
    except Exception as e:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=oauth_failed")

    try:
        user_info = get_user_info(token_data["access_token"])
    except Exception:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=userinfo_failed")

    google_sub = user_info["id"]
    email = user_info["email"]
    name = user_info.get("name", email)
    picture = user_info.get("picture")

    is_new = False
    therapist = db.query(Therapist).filter(Therapist.google_sub == google_sub).first()
    if not therapist:
        therapist = db.query(Therapist).filter(Therapist.email == email).first()

    if not therapist:
        is_new = True
        therapist = Therapist(
            email=email,
            name=name,
            google_sub=google_sub,
            picture_url=picture,
        )
        db.add(therapist)
    else:
        therapist.name = name
        therapist.picture_url = picture
        therapist.google_sub = google_sub

    db.commit()
    db.refresh(therapist)

    access_token = create_access_token(str(therapist.id), "therapist")
    refresh_token = create_refresh_token(str(therapist.id), "therapist")

    # New therapists → onboarding; returning therapists → dashboard
    redirect_url = (
        f"{settings.FRONTEND_URL}/auth/callback"
        f"?access_token={access_token}"
        f"&refresh_token={refresh_token}"
        f"&role=therapist"
        f"&is_new={'true' if is_new or not therapist.onboarding_completed else 'false'}"
    )
    return RedirectResponse(url=redirect_url)


# ─── Client: Email/Password ───────────────────────────────────────────────────

@router.post("/client/register", response_model=TokenResponse)
def client_register(data: ClientRegister, db: Session = Depends(get_db)):
    existing = db.query(Client).filter(Client.email == data.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    client = Client(
        email=data.email,
        name=data.name,
        hashed_password=hash_password(data.password),
        is_active=True,
        email_verified=True,
    )

    if data.invite_token:
        # If registering with invite token, activate and link
        invited = db.query(Client).filter(
            Client.invite_token == data.invite_token,
            Client.invite_token_expires > datetime.utcnow(),
        ).first()
        if invited:
            # Merge: use the pre-created shell client record
            invited.hashed_password = hash_password(data.password)
            invited.is_active = True
            invited.email_verified = True
            invited.invite_token = None
            if data.name:
                invited.name = data.name
            db.commit()
            db.refresh(invited)
            client = invited

    if not client.id:
        db.add(client)
        db.commit()
        db.refresh(client)

    access_token = create_access_token(str(client.id), "client")
    refresh_token = create_refresh_token(str(client.id), "client")
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, role="client")


@router.post("/client/login", response_model=TokenResponse)
def client_login(data: ClientLogin, db: Session = Depends(get_db)):
    client = db.query(Client).filter(Client.email == data.email).first()
    if not client or not verify_password(data.password, client.hashed_password or ""):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not client.is_active:
        raise HTTPException(status_code=403, detail="Account not activated. Check your email.")

    access_token = create_access_token(str(client.id), "client")
    refresh_token = create_refresh_token(str(client.id), "client")
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, role="client")


@router.post("/client/activate", response_model=TokenResponse)
def activate_client_account(data: ActivateAccount, db: Session = Depends(get_db)):
    """Activate an invited client account via one-time token."""
    client = db.query(Client).filter(
        Client.invite_token == data.invite_token,
        Client.invite_token_expires > datetime.utcnow(),
    ).first()
    if not client:
        raise HTTPException(status_code=400, detail="Invalid or expired activation token")

    client.hashed_password = hash_password(data.password)
    client.is_active = True
    client.email_verified = True
    client.invite_token = None
    client.invite_token_expires = None
    if data.name:
        client.name = data.name

    db.commit()
    db.refresh(client)

    access_token = create_access_token(str(client.id), "client")
    refresh_token = create_refresh_token(str(client.id), "client")
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, role="client")


@router.post("/client/forgot-password")
def client_forgot_password(data: ForgotPassword, db: Session = Depends(get_db)):
    client = db.query(Client).filter(Client.email == data.email).first()
    if client:
        code = f"{random.randint(0, 999999):06d}"
        client.reset_token = hash_password(code)
        client.reset_token_expires = datetime.utcnow() + timedelta(minutes=30)
        db.commit()
        try:
            send_password_reset_email(client.email, client.name, code)
        except Exception:
            pass
    return {"message": "If an account with that email exists, a reset code has been sent."}


@router.post("/client/reset-password")
def client_reset_password(data: ResetPassword, db: Session = Depends(get_db)):
    client = db.query(Client).filter(
        Client.email == data.email,
        Client.reset_token_expires > datetime.utcnow(),
    ).first()
    if not client or not client.reset_token or not verify_password(data.code, client.reset_token):
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")
    client.hashed_password = hash_password(data.new_password)
    client.reset_token = None
    client.reset_token_expires = None
    db.commit()
    return {"message": "Password reset successfully"}


@router.post("/admin/login", response_model=TokenResponse)
def admin_login(data: ClientLogin, db: Session = Depends(get_db)):
    admin = db.query(AdminUser).filter(AdminUser.email == data.email).first()
    if not admin or not verify_password(data.password, admin.hashed_password or ""):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not admin.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    access_token = create_access_token(str(admin.id), "admin")
    refresh_token = create_refresh_token(str(admin.id), "admin")
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, role="admin")


@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(refresh_token: str, db: Session = Depends(get_db)):
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Not a refresh token")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    role = payload["role"]
    subject = payload["sub"]

    new_access = create_access_token(subject, role)
    new_refresh = create_refresh_token(subject, role)
    return TokenResponse(access_token=new_access, refresh_token=new_refresh, role=role)
