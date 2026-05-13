import uuid
from datetime import datetime
from sqlalchemy import Column, DateTime, Numeric, ForeignKey, UniqueConstraint, Boolean, Text, String, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class BillingFrequency:
    SAME_DAY = "same_day"
    NEXT_DAY = "next_day"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class TherapistClient(Base):
    __tablename__ = "therapist_clients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    therapist_id = Column(UUID(as_uuid=True), ForeignKey("therapists.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)

    default_session_price = Column(Numeric(10, 2), nullable=False, default=0)
    is_active = Column(Boolean, default=True)
    notes = Column(Text)

    # Billing schedule
    billing_frequency = Column(String(32), nullable=False, default=BillingFrequency.SAME_DAY)
    # For weekly: 0=Mon…6=Sun. For monthly: 1-28 (day of month). Null for same_day/next_day.
    billing_anchor_day = Column(Integer)

    # Tax / VAT — when True, iCount documents are issued at 0% VAT for this client
    tax_exempt = Column(Boolean, nullable=False, server_default='false')

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("therapist_id", "client_id", name="uq_therapist_client"),
    )

    # Relationships
    therapist = relationship("Therapist", back_populates="therapist_clients")
    client = relationship("Client", back_populates="therapist_clients")
