"""
Stores the payme_sale_id → invoice mapping so the PayMe webhook handler
can resolve invoice context. PayMe does not support arbitrary metadata
on payments, so we maintain this table ourselves.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base


class PayMePaymentMetadata(Base):
    __tablename__ = "payme_payment_metadata"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payme_sale_id = Column(String(255), unique=True, nullable=False, index=True)
    invoice_id    = Column(UUID(as_uuid=True), ForeignKey("invoices.id",    ondelete="CASCADE"), nullable=False, index=True)
    therapist_id  = Column(UUID(as_uuid=True), ForeignKey("therapists.id",  ondelete="CASCADE"), nullable=False)
    client_id     = Column(UUID(as_uuid=True), ForeignKey("clients.id",     ondelete="CASCADE"), nullable=False)
    extra_data    = Column("metadata", JSONB, default=dict)
    created_at    = Column(DateTime(timezone=True), default=datetime.utcnow)
