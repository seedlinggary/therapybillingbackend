import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy import Index
from app.database import Base


class AuditLog(Base):
    __tablename__ = "accounting_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    therapist_id = Column(UUID(as_uuid=True), ForeignKey("therapists.id", ondelete="SET NULL"),
                          nullable=True, index=True)
    action = Column(String(64), nullable=False)
    # create_invoice | create_receipt | cancel_document | resend_email | retry | connect | disconnect
    status = Column(String(16), nullable=False)         # 'success' | 'failed'
    entity_type = Column(String(32))                    # 'document' | 'integration'
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    error_message = Column(Text)
    log_metadata = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        Index("ix_audit_logs_therapist_created", "therapist_id", "created_at"),
    )
