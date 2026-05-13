import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey, Text, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class AppointmentStatus:
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELED = "canceled"
    NO_SHOW = "no_show"


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    therapist_id = Column(UUID(as_uuid=True), ForeignKey("therapists.id", ondelete="RESTRICT"), nullable=False, index=True)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False, index=True)
    recurrence_id = Column(UUID(as_uuid=True), ForeignKey("recurrence_rules.id", ondelete="SET NULL"), nullable=True, index=True)

    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)

    status = Column(String(32), nullable=False, default=AppointmentStatus.SCHEDULED, index=True)
    completed_at = Column(DateTime(timezone=True))
    canceled_at = Column(DateTime(timezone=True))

    # Pricing
    override_price = Column(Numeric(10, 2))
    session_type = Column(String(128), default="Individual")

    # Billing state — the authoritative guard against duplicate billing
    billed = Column(Boolean, nullable=False, default=False, index=True)

    # Google Calendar
    google_event_id = Column(String(255))
    google_calendar_id = Column(String(255))

    # Session notes (therapist only)
    session_notes = Column(Text)

    # VAT / tax-exempt override. NULL = use client's TherapistClient.tax_exempt default.
    tax_exempt = Column(Boolean, nullable=True)

    # Cancellation
    cancellation_reason = Column(Text)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_appointments_therapist_start", "therapist_id", "start_time"),
        Index("ix_appointments_client_start", "client_id", "start_time"),
        Index("ix_appointments_status_completed", "status", "completed_at"),
        Index("ix_appointments_billed", "status", "billed", "completed_at"),
    )

    # Relationships
    therapist = relationship("Therapist", back_populates="appointments")
    client = relationship("Client", back_populates="appointments")
    recurrence_rule = relationship("RecurrenceRule", back_populates="appointments")
    invoice = relationship("Invoice", back_populates="appointment", uselist=False)
    invoice_items = relationship("InvoiceItem", back_populates="appointment")
