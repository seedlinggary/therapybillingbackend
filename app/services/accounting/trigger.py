"""
Shared accounting trigger helpers — called whenever an invoice changes state.
Kept here so both the Stripe webhook handler and the invoices router can import
the same logic without circular dependencies.
"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.invoice import Invoice
from app.models.accounting_document import AccountingDocument, DocumentStatus, DocumentType
from app.models.audit_log import AuditLog
from app.models.retry_job import RetryJob
from app.models.therapist import Therapist
from app.models.therapist_client import TherapistClient
from .factory import get_accounting_service
from .base import DocumentPayload
from app.services.exchange_rate import get_rate

IL_VAT_RATE = 0.18


def _client_vat_rate(invoice: Invoice, db: Session) -> float:
    """
    Return 0.0 (exempt) or IL_VAT_RATE.
    Appointment-level tax_exempt takes precedence over client default.
    """
    # Single-appointment invoice: use the appointment's explicit setting if present
    if invoice.appointment is not None and invoice.appointment.tax_exempt is not None:
        return 0.0 if invoice.appointment.tax_exempt else IL_VAT_RATE

    # Fall back to the client's default on the therapist-client relationship
    rel = db.query(TherapistClient).filter(
        TherapistClient.therapist_id == invoice.therapist_id,
        TherapistClient.client_id == invoice.client_id,
    ).first()
    if rel and getattr(rel, "tax_exempt", False):
        return 0.0
    return IL_VAT_RATE

logger = logging.getLogger(__name__)


def issue_accounting_invoice(invoice: Invoice, therapist: Therapist, db: Session) -> None:
    """
    For Israeli therapists: create an iCount tax invoice when the invoice is first issued.
    The resulting docnum is stored so a receipt (קבלה) can reference it when paid.
    Never raises — must not block the caller.
    """
    try:
        country = (getattr(therapist, "country", "US") or "US").upper()
        if country != "IL":
            return

        client = invoice.client
        description = f"Therapy Session — Invoice #{invoice.invoice_number}"
        if invoice.items:
            description = f"Therapy — {len(invoice.items)} session(s)"

        inv_currency = getattr(invoice, "currency", None) or "ILS"
        exchange_rate = get_rate("USD", "ILS") if inv_currency == "USD" else None
        if inv_currency == "USD" and exchange_rate is None:
            logger.warning("Could not fetch USD→ILS exchange rate; iCount invoice amount may be incorrect")

        payload = DocumentPayload(
            client_name=client.name if client else "",
            client_email=client.email if client else "",
            amount=float(invoice.amount),
            currency=inv_currency,
            description=description,
            invoice_number=invoice.invoice_number,
            payment_method="online",
            vat_rate=_client_vat_rate(invoice, db),
            exchange_rate=exchange_rate,
        )

        service = get_accounting_service(therapist, db)
        result = service.create_invoice(payload)

        meta: dict = {
            "client_name": payload.client_name,
            "client_email": payload.client_email,
            "invoice_number": invoice.invoice_number,
        }
        if not result.success and result.error:
            meta["provider_error"] = result.error
        if not result.success and result.raw_response:
            meta["provider_raw_response"] = result.raw_response

        doc = AccountingDocument(
            therapist_id=therapist.id,
            invoice_id=invoice.id,
            doc_type=DocumentType.INVOICE,
            external_id=result.external_id if result.success else None,
            pdf_url=result.pdf_url if result.success else None,
            status=DocumentStatus.ISSUED if result.success else DocumentStatus.FAILED,
            amount=invoice.amount,
            currency=inv_currency,
            vat_amount=result.vat_amount if result.success else None,
            doc_metadata=meta,
        )
        db.add(doc)
        db.add(AuditLog(
            therapist_id=therapist.id,
            action="create_invoice",
            status="success" if result.success else "failed",
            entity_type="document",
            entity_id=doc.id if result.success else None,
            error_message=result.error if not result.success else None,
        ))
        db.commit()
        logger.info(f"iCount invoice {'issued' if result.success else 'failed'} for invoice {invoice.id}")
    except Exception as e:
        logger.error(f"issue_accounting_invoice failed for invoice {invoice.id}: {e}", exc_info=True)


def issue_accounting_receipt(invoice: Invoice, db: Session,
                             payment_method: str = "online") -> None:
    """
    Issue an accounting receipt after an invoice is marked paid.
    For IL: creates a receipt (קבלה) referencing the existing iCount invoice if one
    was issued at send-time; falls back to receipt_invoice if not.
    For US: creates a plain receipt via the US accounting service.
    Never raises — must not block the caller.
    """
    try:
        therapist = db.query(Therapist).filter(Therapist.id == invoice.therapist_id).first()
        if not therapist:
            return

        country = (getattr(therapist, "country", "US") or "US").upper()
        client = invoice.client
        inv_currency = getattr(invoice, "currency", None) or ("ILS" if country == "IL" else "USD")
        exchange_rate = get_rate("USD", "ILS") if (country == "IL" and inv_currency == "USD") else None
        if country == "IL" and inv_currency == "USD" and exchange_rate is None:
            logger.warning("Could not fetch USD→ILS exchange rate; iCount receipt amount may be incorrect")

        description = f"Therapy Session — Invoice #{invoice.invoice_number}"
        if invoice.items:
            description = f"Therapy — {len(invoice.items)} session(s)"

        payload = DocumentPayload(
            client_name=client.name if client else "",
            client_email=client.email if client else "",
            amount=float(invoice.amount),
            currency=inv_currency,
            description=description,
            invoice_number=invoice.invoice_number,
            payment_method=payment_method,
            vat_rate=_client_vat_rate(invoice, db) if country == "IL" else 0.0,
            exchange_rate=exchange_rate,
        )

        service = get_accounting_service(therapist, db)

        if country == "IL":
            # Look up the iCount invoice issued at send-time.
            # If found, create a receipt (קבלה) referencing it; otherwise fall back to receipt_invoice.
            existing_invoice_doc = (
                db.query(AccountingDocument)
                .filter(
                    AccountingDocument.invoice_id == invoice.id,
                    AccountingDocument.doc_type == DocumentType.INVOICE,
                    AccountingDocument.status == DocumentStatus.ISSUED,
                )
                .first()
            )
            if existing_invoice_doc and existing_invoice_doc.external_id:
                payload.original_external_id = existing_invoice_doc.external_id
                result = service.create_receipt(payload)
                doc_type = DocumentType.RECEIPT
            else:
                result = service.create_receipt_invoice(payload)
                doc_type = DocumentType.RECEIPT_INVOICE
        else:
            result = service.create_receipt(payload)
            doc_type = DocumentType.RECEIPT

        vat = round(float(invoice.amount) * 0.18 / 1.18, 2) if country == "IL" else None
        meta: dict = {
            "client_name": payload.client_name,
            "client_email": payload.client_email,
            "invoice_number": invoice.invoice_number,
            "payment_method": payment_method,
        }
        if not result.success:
            if result.error:
                meta["provider_error"] = result.error
            if result.raw_response:
                meta["provider_raw_response"] = result.raw_response

        doc = AccountingDocument(
            therapist_id=therapist.id,
            invoice_id=invoice.id,
            doc_type=doc_type,
            external_id=result.external_id if result.success else None,
            pdf_url=result.pdf_url if result.success else None,
            status=DocumentStatus.ISSUED if result.success else DocumentStatus.FAILED,
            amount=invoice.amount,
            currency=payload.currency,
            vat_amount=vat,
            doc_metadata=meta,
        )
        db.add(doc)
        db.flush()

        if not result.success:
            db.add(RetryJob(
                therapist_id=therapist.id,
                document_id=doc.id,
                job_type="create_receipt",
                payload={**meta, "amount": float(invoice.amount), "currency": payload.currency,
                         "description": description},
                status="pending",
                next_attempt_at=datetime.utcnow(),
            ))

        db.add(AuditLog(
            therapist_id=therapist.id,
            action="create_receipt",
            status="success" if result.success else "failed",
            entity_type="document",
            entity_id=doc.id,
            error_message=result.error if not result.success else None,
        ))
        db.commit()
        logger.info(f"Accounting receipt {'issued' if result.success else 'queued for retry'} "
                    f"for invoice {invoice.id}")
    except Exception as e:
        logger.error(f"issue_accounting_receipt failed for invoice {invoice.id}: {e}", exc_info=True)
