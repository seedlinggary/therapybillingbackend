import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class InvoiceStatus:
    UNPAID = "unpaid"
    PAID = "paid"
    VOID = "void"
    REFUNDED = "refunded"


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    therapist_id = Column(UUID(as_uuid=True), ForeignKey("therapists.id", ondelete="RESTRICT"), nullable=False, index=True)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False, index=True)
    # nullable: single-appointment invoices set this; aggregated invoices may leave it null
    appointment_id = Column(UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="RESTRICT"), nullable=True)

    invoice_number = Column(String(64), unique=True, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), nullable=False, server_default='USD')
    status = Column(String(32), nullable=False, default=InvoiceStatus.UNPAID, index=True)

    due_date = Column(DateTime(timezone=True), nullable=False)
    paid_at = Column(DateTime(timezone=True))

    # Stripe
    stripe_payment_intent_id = Column(String(255))
    stripe_payment_link = Column(Text)
    stripe_checkout_session_id = Column(String(255))

    # PDF
    pdf_path = Column(String(500))

    notes = Column(Text)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_invoices_therapist_status", "therapist_id", "status"),
        Index("ix_invoices_client_status", "client_id", "status"),
    )

    # Relationships
    therapist = relationship("Therapist", back_populates="invoices")
    client = relationship("Client", back_populates="invoices")
    appointment = relationship("Appointment", back_populates="invoice", foreign_keys=[appointment_id])
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice")
