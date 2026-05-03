import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Text, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy import Index
from app.database import Base


class RetryJob(Base):
    __tablename__ = "accounting_retry_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    therapist_id = Column(UUID(as_uuid=True), ForeignKey("therapists.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("accounting_documents.id", ondelete="CASCADE"),
                         nullable=True)

    job_type = Column(String(64), nullable=False)
    # create_receipt | create_invoice | create_credit_note | resend_email

    payload = Column(JSON, nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    # pending | retrying | succeeded | failed

    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=6)
    last_error = Column(Text)
    next_attempt_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_retry_jobs_status_next", "status", "next_attempt_at"),
    )

    # Relationships
    document = relationship("AccountingDocument", back_populates="retry_jobs")
