import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class ServiceType(Base):
    __tablename__ = "service_types"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    therapist_id = Column(UUID(as_uuid=True), ForeignKey("therapists.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    duration_minutes = Column(Integer(), nullable=False, default=50)
    is_active = Column(Boolean(), nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    therapist = relationship("Therapist", back_populates="service_types")
