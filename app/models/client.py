import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Client(Base):
    __tablename__ = "clients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    hashed_password = Column(String(255))
    phone = Column(String(32))

    # Account state
    is_active = Column(Boolean, default=False)  # False until email verified / invite accepted
    email_verified = Column(Boolean, default=False)
    invite_token = Column(String(255), index=True)  # one-time token for account activation
    invite_token_expires = Column(DateTime(timezone=True))

    # Password reset (6-digit code, hashed)
    reset_token = Column(String(255))
    reset_token_expires = Column(DateTime(timezone=True))

    # Profile
    date_of_birth = Column(DateTime(timezone=True))
    address = Column(Text)
    timezone = Column(String(64), default="America/New_York")
    notes = Column(Text)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    therapist_clients = relationship("TherapistClient", back_populates="client")
    appointments = relationship("Appointment", back_populates="client")
    invoices = relationship("Invoice", back_populates="client")
    recurrence_rules = relationship("RecurrenceRule", back_populates="client")
