from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError
from app.database import get_db
from app.core.security import decode_token
from app.models.therapist import Therapist
from app.models.client import Client
from app.models.admin_user import AdminUser
import uuid

bearer_scheme = HTTPBearer()


def _get_token_data(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    try:
        return decode_token(credentials.credentials)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def get_current_therapist(
    token_data: dict = Depends(_get_token_data),
    db: Session = Depends(get_db),
) -> Therapist:
    if token_data.get("role") != "therapist":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Therapist access required")
    therapist = db.query(Therapist).filter(Therapist.id == uuid.UUID(token_data["sub"])).first()
    if not therapist or not therapist.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Therapist not found")
    return therapist


def get_current_client(
    token_data: dict = Depends(_get_token_data),
    db: Session = Depends(get_db),
) -> Client:
    if token_data.get("role") != "client":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client access required")
    client = db.query(Client).filter(Client.id == uuid.UUID(token_data["sub"])).first()
    if not client or not client.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Client not found")
    return client


def get_current_admin(
    token_data: dict = Depends(_get_token_data),
    db: Session = Depends(get_db),
) -> AdminUser:
    if token_data.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    admin = db.query(AdminUser).filter(AdminUser.id == uuid.UUID(token_data["sub"])).first()
    if not admin or not admin.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin not found")
    return admin


def get_current_user(
    token_data: dict = Depends(_get_token_data),
    db: Session = Depends(get_db),
):
    """Returns either a Therapist or Client depending on role."""
    role = token_data.get("role")
    if role == "therapist":
        return get_current_therapist(token_data, db)
    elif role == "client":
        return get_current_client(token_data, db)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown role")
