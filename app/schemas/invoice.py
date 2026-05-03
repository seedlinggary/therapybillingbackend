from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid


class InvoiceItemResponse(BaseModel):
    id: uuid.UUID
    appointment_id: uuid.UUID
    amount: float
    description: str
    appointment_start: Optional[datetime] = None

    class Config:
        from_attributes = True


class InvoiceResponse(BaseModel):
    id: uuid.UUID
    invoice_number: str
    therapist_id: uuid.UUID
    therapist_name: Optional[str] = None
    client_id: uuid.UUID
    client_name: Optional[str] = None
    appointment_id: Optional[uuid.UUID] = None   # nullable for multi-appointment invoices
    appointment_start: Optional[datetime] = None  # first session date (for display)
    items: List[InvoiceItemResponse] = []
    amount: float
    currency: str = "USD"
    status: str
    due_date: datetime
    paid_at: Optional[datetime] = None
    stripe_payment_link: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class InvoiceCreate(BaseModel):
    appointment_id: uuid.UUID
    due_date: Optional[datetime] = None
    notes: Optional[str] = None


class InvoiceListFilter(BaseModel):
    status: Optional[str] = None
    client_id: Optional[uuid.UUID] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
