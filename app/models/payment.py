import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Payment(Base):
    __tablename__ = "payments"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False, index=True)

    # Universal provider-agnostic fields
    provider            = Column(String(32), nullable=False, server_default='stripe')
    external_payment_id = Column(String(255), unique=True, nullable=True, index=True)

    amount         = Column(Numeric(10, 2), nullable=False)
    status         = Column(String(32), nullable=False)  # succeeded, failed, refunded
    failure_reason = Column(Text)

    # Stripe-specific (nullable for non-Stripe payments)
    stripe_payment_intent_id = Column(String(255), unique=True, nullable=True)
    stripe_charge_id         = Column(String(255))

    paid_at    = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    invoice = relationship("Invoice", back_populates="payments")
