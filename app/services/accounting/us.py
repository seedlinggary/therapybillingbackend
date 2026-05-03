"""
US accounting service — internal implementation, no external API.

Uses the existing pdf_service to generate PDFs and stores them locally.
No VAT. Documents are stored in the accounting_documents table only.
"""
import logging
import os
import uuid as uuid_mod
from datetime import datetime

from .base import BaseAccountingService, AccountingResult, DocumentPayload
from app.services.pdf_service import generate_invoice_pdf

logger = logging.getLogger(__name__)

PDF_OUTPUT_DIR = os.environ.get("PDF_OUTPUT_DIR", "/tmp/receipts")


class USAccountingService(BaseAccountingService):
    """
    Internal PDF-based accounting for US therapists.
    No VAT, no external API, documents generated on-demand.
    """

    def _generate_pdf(self, doc_type: str, payload: DocumentPayload) -> AccountingResult:
        try:
            os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
            doc_id = str(uuid_mod.uuid4())
            filename = f"{doc_type}_{doc_id}.pdf"
            path = os.path.join(PDF_OUTPUT_DIR, filename)

            # Reuse the existing invoice PDF generator
            generate_invoice_pdf(
                output_path=path,
                invoice_number=payload.invoice_number,
                client_name=payload.client_name,
                therapist_name="",          # caller fills via metadata if needed
                amount=payload.amount,
                description=payload.description,
                doc_type=doc_type.replace("_", " ").title(),
            )

            # In production, upload to S3/GCS and return a signed URL here.
            # For now, return the local path as a relative URL.
            pdf_url = f"/internal/receipts/{filename}"

            logger.info(f"US {doc_type} generated: {filename}")
            return AccountingResult(
                success=True,
                external_id=doc_id,
                pdf_url=pdf_url,
                vat_amount=0.0,
            )
        except Exception as e:
            logger.error(f"US PDF generation failed ({doc_type}): {e}")
            return AccountingResult(success=False, error=str(e))

    def create_invoice(self, payload: DocumentPayload) -> AccountingResult:
        return self._generate_pdf("invoice", payload)

    def create_receipt(self, payload: DocumentPayload) -> AccountingResult:
        return self._generate_pdf("receipt", payload)

    def create_receipt_invoice(self, payload: DocumentPayload) -> AccountingResult:
        # In the US there is no legal combined document — generate a receipt
        return self.create_receipt(payload)

    def create_credit_note(self, payload: DocumentPayload) -> AccountingResult:
        return self._generate_pdf("credit_note", payload)

    def cancel_document(self, external_id: str) -> AccountingResult:
        # Internal docs have no provider to notify — just mark canceled in DB (router handles this)
        return AccountingResult(success=True, external_id=external_id)

    def get_pdf(self, external_id: str) -> AccountingResult:
        # The pdf_url is stored in accounting_documents when created
        return AccountingResult(success=True, external_id=external_id)

    def resend_email(self, external_id: str, client_email: str) -> AccountingResult:
        # Email is sent by the router using the existing email_service
        return AccountingResult(success=True, external_id=external_id)
