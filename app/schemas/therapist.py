from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
import uuid


class TherapistProfile(BaseModel):
    id: uuid.UUID
    email: EmailStr
    name: str
    picture_url: Optional[str] = None
    business_type: Optional[str] = None
    timezone: str
    phone: Optional[str] = None
    license_number: Optional[str] = None
    bio: Optional[str] = None
    payment_instructions: Optional[str] = None
    country: str = "US"
    default_currency: str = "USD"
    default_session_price: Optional[float] = None
    default_billing_frequency: str = "same_day"
    default_billing_anchor_day: Optional[int] = None
    google_calendar_connected: bool
    stripe_connected: bool
    onboarding_completed: bool
    payment_provider: str = "stripe"
    payme_seller_id: Optional[str] = None
    paypal_email: Optional[str] = None
    paypal_connected: bool = False
    show_conversion_note: bool = False
    reminder_frequency_days: Optional[int] = None
    reminder_repeat: bool = True
    accounting_send_email_invoice: bool = False
    accounting_send_email_receipt: bool = True
    dashboard_note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TherapistUpdate(BaseModel):
    name: Optional[str] = None
    business_type: Optional[str] = None
    timezone: Optional[str] = None
    phone: Optional[str] = None
    license_number: Optional[str] = None
    bio: Optional[str] = None
    payment_instructions: Optional[str] = None
    country: Optional[str] = None
    default_currency: Optional[str] = None
    default_session_price: Optional[float] = None
    default_billing_frequency: Optional[str] = None
    default_billing_anchor_day: Optional[int] = None
    payment_provider: Optional[str] = None
    payme_seller_id: Optional[str] = None
    payme_api_key: Optional[str] = None
    paypal_email: Optional[str] = None
    paypal_connected: Optional[bool] = None
    show_conversion_note: Optional[bool] = None
    reminder_frequency_days: Optional[int] = None
    reminder_repeat: Optional[bool] = None
    accounting_send_email_invoice: Optional[bool] = None
    accounting_send_email_receipt: Optional[bool] = None
    dashboard_note: Optional[str] = None


class TherapistOnboardingStatus(BaseModel):
    google_calendar_connected: bool
    stripe_connected: bool
    onboarding_completed: bool
