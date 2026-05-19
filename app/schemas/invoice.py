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
    payment_provider: str = "stripe"
    payment_link: Optional[str] = None          # provider-agnostic — use this in UI
    stripe_payment_link: Optional[str] = None   # kept for backward compat
    created_at: datetime

    class Config:
        from_attributes = True


class InvoiceCreate(BaseModel):
    appointment_id: uuid.UUID
    due_date: Optional[datetime] = None
    notes: Optional[str] = None


class MarkPaidRequest(BaseModel):
    payment_method: str = "cash"   # cash | bank_transfer | check | credit_card
    payment_date: Optional[str] = None  # YYYY-MM-DD; defaults to today if omitted


class InvoiceListFilter(BaseModel):
    status: Optional[str] = None
    client_id: Optional[uuid.UUID] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
