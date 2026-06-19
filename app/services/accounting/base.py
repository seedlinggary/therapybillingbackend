"""
Abstract base for all accounting/invoicing service implementations.
Each country-specific class inherits this and must implement every method.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class AccountingResult:
    success: bool
    external_id: Optional[str] = None      # provider-assigned document ID
    pdf_url: Optional[str] = None
    vat_amount: Optional[float] = None
    raw_response: Optional[Dict[str, Any]] = field(default=None, repr=False)
    error: Optional[str] = None


@dataclass
class DocumentPayload:
    client_name: str
    client_email: str
    amount: float
    currency: str
    description: str
    invoice_number: str
    payment_method: str = "online"          # online | cash | bank_transfer | check | credit_card
    line_items: Optional[list] = None       # [{description, amount, quantity}]
    vat_rate: float = 0.0                   # 0.18 for IL
    original_external_id: Optional[str] = None  # for credit notes
    exchange_rate: Optional[float] = None   # USD→ILS rate for IL therapists billing in USD
    payment_date: Optional[str] = None      # ISO date string YYYY-MM-DD; defaults to today if None
    send_email: Optional[bool] = None       # None = use doc-type default (receipts→True, invoices→False)


class BaseAccountingService(ABC):

    @abstractmethod
    def create_invoice(self, payload: DocumentPayload) -> AccountingResult:
        """Issue a tax invoice (חשבונית מס). Called before payment."""
        ...

    @abstractmethod
    def create_receipt(self, payload: DocumentPayload) -> AccountingResult:
        """Issue a receipt (קבלה). Called after payment confirmed."""
        ...

    @abstractmethod
    def create_receipt_invoice(self, payload: DocumentPayload) -> AccountingResult:
        """Issue a combined receipt-invoice (חשבונית מס קבלה). IL only."""
        ...

    @abstractmethod
    def create_credit_note(self, payload: DocumentPayload) -> AccountingResult:
        """Issue a credit note (זיכוי) against an existing document."""
        ...

    @abstractmethod
    def cancel_document(self, external_id: str) -> AccountingResult:
        """Cancel/void a document by its external provider ID."""
        ...

    @abstractmethod
    def get_pdf(self, external_id: str) -> AccountingResult:
        """Retrieve PDF URL (or bytes path) for a document."""
        ...

    @abstractmethod
    def resend_email(self, external_id: str, client_email: str) -> AccountingResult:
        """Ask the provider to resend the document email to the client."""
        ...
