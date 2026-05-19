from pydantic import BaseModel, model_validator
from typing import Optional, Any, Dict, List
from datetime import datetime
import uuid


# ── Integration ───────────────────────────────────────────────────────────────

class AccountingConnectRequest(BaseModel):
    provider: str                           # 'icount' | 'green_invoice'
    company_id: str                         # iCount: cid  |  Green Invoice: API key ID
    username: str = ""                      # iCount: username  |  Green Invoice: unused
    api_key: str                            # iCount: password  |  Green Invoice: API key secret


class AccountingIntegrationStatus(BaseModel):
    id: uuid.UUID
    provider: str
    company_id: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Document ──────────────────────────────────────────────────────────────────

class AccountingDocumentOut(BaseModel):
    id: uuid.UUID
    invoice_id: Optional[uuid.UUID] = None
    parent_document_id: Optional[uuid.UUID] = None
    doc_type: str
    external_id: Optional[str] = None
    pdf_url: Optional[str] = None
    status: str
    amount: float
    currency: str
    vat_amount: Optional[float] = None
    doc_metadata: Optional[Dict[str, Any]] = None
    provider_error: Optional[str] = None       # populated when status == 'failed'
    created_at: datetime
    updated_at: datetime

    @model_validator(mode='after')
    def extract_provider_error(self) -> 'AccountingDocumentOut':
        if self.provider_error is None and self.doc_metadata:
            self.provider_error = self.doc_metadata.get("provider_error")
        return self

    class Config:
        from_attributes = True


class ManualReceiptRequest(BaseModel):
    invoice_id: Optional[uuid.UUID] = None
    amount: float
    currency: str = "USD"
    client_name: str
    client_email: str
    description: Optional[str] = None
    payment_method: str = "cash"            # cash | bank_transfer | check | other
    doc_type: Optional[str] = None          # override: invoice|receipt|receipt_invoice|credit_note


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    id: uuid.UUID
    action: str
    status: str
    entity_type: Optional[str] = None
    entity_id: Optional[uuid.UUID] = None
    error_message: Optional[str] = None
    log_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Reports ───────────────────────────────────────────────────────────────────

class MonthlyReportRow(BaseModel):
    month: str                              # "2026-04"
    total_amount: float
    total_vat: float
    document_count: int
    currency: str


class MonthlyReportOut(BaseModel):
    rows: List[MonthlyReportRow]
    grand_total: float
    grand_vat: float
