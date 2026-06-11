import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Boolean, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Therapist(Base):
    __tablename__ = "therapists"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    google_sub = Column(String(255), unique=True, nullable=False, index=True)
    picture_url = Column(String(500))

    # Encrypted at rest using Fernet
    google_access_token_enc = Column(Text)
    google_refresh_token_enc = Column(Text)
    google_token_expiry = Column(DateTime(timezone=True))
    google_calendar_id = Column(String(255))
    google_calendar_connected = Column(Boolean, default=False)

    # Active payment provider: 'stripe' | 'payme' | 'paypal'
    payment_provider = Column(String(32), nullable=False, server_default='stripe')

    # Stripe Connect
    stripe_account_id = Column(String(255), unique=True, index=True)
    stripe_connected  = Column(Boolean, default=False)

    # PayMe credentials (store api_key encrypted in production)
    payme_seller_id = Column(String(255))
    payme_api_key   = Column(Text)

    # PayPal credentials
    paypal_email     = Column(String(255))
    paypal_connected = Column(Boolean, default=False)

    # Profile
    business_type = Column(String(128), nullable=True)
    timezone = Column(String(64), default="Asia/Jerusalem")
    phone = Column(String(32))
    license_number = Column(String(64))
    bio = Column(Text)
    payment_instructions = Column(Text)  # shown on all invoices (Zelle, bank transfer, etc.)

    # Country determines compliance rules: 'US' = internal, 'IL' = iCount (regulated)
    country = Column(String(8), nullable=False, server_default='US')

    # Currency: drives Stripe, invoices, and accounting
    default_currency = Column(String(3), nullable=False, server_default='USD')
    # USD→ILS exchange rate used for iCount when billing in USD from IL account
    ils_exchange_rate = Column(Numeric(10, 4), server_default='3.70')

    # Global default session price — copied to new client relationships; fallback for _resolve_amount
    default_session_price = Column(Numeric(10, 2))

    # Default billing schedule applied to new clients (can be overridden per-client)
    default_billing_frequency = Column(String(32), nullable=False, server_default='same_day')
    default_billing_anchor_day = Column(Integer)  # 0-6 for weekly, 1-28 for monthly

    show_conversion_note = Column(Boolean, nullable=False, server_default='false')

    # Payment reminders — null/0 = disabled; >0 = send every N days to clients with unpaid invoices
    reminder_frequency_days = Column(Integer, nullable=True)
    last_payment_reminder_at = Column(DateTime(timezone=True), nullable=True)
    # True = keep sending every N days until paid; False = send once per client then stop
    reminder_repeat = Column(Boolean, nullable=False, server_default='true')

    # Dashboard general note
    dashboard_note = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)
    onboarding_completed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    therapist_clients = relationship("TherapistClient", back_populates="therapist", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="therapist")
    invoices = relationship("Invoice", back_populates="therapist")
    recurrence_rules = relationship("RecurrenceRule", back_populates="therapist")
    service_types = relationship("ServiceType", back_populates="therapist", cascade="all, delete-orphan")
