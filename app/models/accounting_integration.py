import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class AccountingIntegration(Base):
    __tablename__ = "accounting_integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    therapist_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    provider = Column(String(32), nullable=False)       # 'icount' | 'internal'
    access_token_enc = Column(Text)                     # Fernet-encrypted API key / password
    company_id = Column(String(128))                    # iCount company ID (cid)
    username_enc = Column(Text)                         # Fernet-encrypted username (iCount user)
    is_active = Column(Boolean, nullable=False, default=True)
    # GreenInvoice document type: 'invoice' (305), 'receipt_invoice' (320), 'receipt' (400)
    green_invoice_doc_type = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('therapist_id', 'provider', name='uq_accounting_therapist_provider'),
    )
