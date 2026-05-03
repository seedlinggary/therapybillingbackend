import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, DateTime, Date, Numeric, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class RecurrenceRule(Base):
    __tablename__ = "recurrence_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    therapist_id = Column(UUID(as_uuid=True), ForeignKey("therapists.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)

    recurrence_type = Column(String(32), nullable=False)  # daily, weekly, biweekly, monthly
    interval = Column(Integer, nullable=False, default=1)  # e.g. every 2 weeks
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)                # NULL if using occurrence_count
    occurrence_count = Column(Integer)     # NULL if using end_date

    # Template fields for generated appointments
    session_type = Column(String(128), default="Individual")
    override_price = Column(Numeric(10, 2))
    duration_minutes = Column(Integer, nullable=False, default=50)
    start_hour = Column(Integer, nullable=False, default=10)   # 24h local hour
    start_minute = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    therapist = relationship("Therapist", back_populates="recurrence_rules")
    client = relationship("Client", back_populates="recurrence_rules")
    appointments = relationship("Appointment", back_populates="recurrence_rule")
