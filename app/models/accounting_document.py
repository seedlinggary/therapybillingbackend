import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Numeric, Text, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class DocumentStatus:
    PENDING = "pending"
    ISSUED = "issued"
    CANCELED = "canceled"
    FAILED = "failed"


class DocumentType:
    INVOICE = "invoice"
    RECEIPT = "receipt"
    RECEIPT_INVOICE = "receipt_invoice"   # חשבונית מס קבלה — Israel combined doc
    CREDIT_NOTE = "credit_note"


class AccountingDocument(Base):
    __tablename__ = "accounting_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    therapist_id = Column(UUID(as_uuid=True), ForeignKey("therapists.id", ondelete="RESTRICT"),
                          nullable=False, index=True)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="SET NULL"),
                        nullable=True, index=True)
    parent_document_id = Column(UUID(as_uuid=True),
                                ForeignKey("accounting_documents.id", ondelete="SET NULL"),
                                nullable=True)

    doc_type = Column(String(32), nullable=False)
    external_id = Column(String(255))
    pdf_url = Column(Text)
    status = Column(String(32), nullable=False, default=DocumentStatus.PENDING)

    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(8), nullable=False, default="USD")
    vat_amount = Column(Numeric(10, 2))

    doc_metadata = Column(JSON)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Self-referential: credit note → original document it cancels.
    # remote_side on the many-to-one side (parent_document) marks `id` as the "one" end.
    parent_document = relationship(
        "AccountingDocument",
        foreign_keys="[AccountingDocument.parent_document_id]",
        back_populates="credit_notes",
        remote_side="[AccountingDocument.id]",
    )
    credit_notes = relationship(
        "AccountingDocument",
        foreign_keys="[AccountingDocument.parent_document_id]",
        back_populates="parent_document",
    )

    retry_jobs = relationship("RetryJob", back_populates="document", cascade="all, delete-orphan")
