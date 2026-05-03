from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime
import uuid


class ClientRegister(BaseModel):
    email: EmailStr
    name: str
    password: str
    invite_token: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class ClientLogin(BaseModel):
    email: EmailStr
    password: str


class ClientCreate(BaseModel):
    """Therapist creates a client (sends invite)."""
    email: EmailStr
    name: str
    default_session_price: float
    phone: Optional[str] = None
    notes: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


class ClientProfile(BaseModel):
    id: uuid.UUID
    email: EmailStr
    name: str
    phone: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TherapistClientDetail(BaseModel):
    """Client as seen from therapist's perspective."""
    id: uuid.UUID
    client_id: uuid.UUID
    email: EmailStr
    name: str
    phone: Optional[str]
    default_session_price: float
    is_active: bool
    notes: Optional[str]
    client_is_active: bool
    billing_frequency: str = "same_day"
    billing_anchor_day: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TherapistClientUpdate(BaseModel):
    default_session_price: Optional[float] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class TherapistClientBillingUpdate(BaseModel):
    billing_frequency: Optional[str] = None
    billing_anchor_day: Optional[int] = None


class ForgotPassword(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    email: EmailStr
    code: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str


class ActivateAccount(BaseModel):
    invite_token: str
    password: str
    name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v
