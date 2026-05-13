"""
Accounting integration router.

All endpoints require therapist authentication.
Country-aware: IL therapists must connect iCount before issuing legal documents.
"""
import csv
import io
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.deps import get_current_therapist, get_db
from app.core.security import encrypt_token
from app.models.accounting_document import AccountingDocument, DocumentStatus, DocumentType
from app.models.accounting_integration import AccountingIntegration
from app.models.audit_log import AuditLog
from app.models.invoice import Invoice
from app.models.retry_job import RetryJob
from app.schemas.accounting import (
    AccountingConnectRequest, AccountingIntegrationStatus,
    AccountingDocumentOut, ManualReceiptRequest,
    AuditLogOut, MonthlyReportOut, MonthlyReportRow,
)
from app.services.accounting import get_accounting_service
from app.services.accounting.base import DocumentPayload
from app.services.accounting.israel import ICountAccountingService
from app.services.email_service import send_invoice_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations/accounting", tags=["accounting"])
docs_router = APIRouter(prefix="/documents", tags=["documents"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(db: Session, therapist_id, action: str, status: str,
         entity_type: str = None, entity_id=None,
         error: str = None, metadata: dict = None):
    db.add(AuditLog(
        therapist_id=therapist_id,
        action=action,
        status=status,
        entity_type=entity_type,
        entity_id=entity_id,
        error_message=error,
        log_metadata=metadata,
    ))


def _enqueue_retry(db: Session, therapist_id, document_id, job_type: str, payload: dict):
    """Schedule a job for first retry in 1 minute."""
    db.add(RetryJob(
        therapist_id=therapist_id,
        document_id=document_id,
        job_type=job_type,
        payload=payload,
        status="pending",
        attempts=0,
        next_attempt_at=datetime.utcnow() + timedelta(minutes=1),
    ))


# ── Integration endpoints ─────────────────────────────────────────────────────

@router.post("/connect", response_model=AccountingIntegrationStatus)
def connect_accounting(
    body: AccountingConnectRequest,
    therapist=Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    """Store encrypted credentials for an accounting provider (iCount, etc.)."""
    if body.provider == "icount":
        svc = ICountAccountingService(
            company_id=body.company_id,
            username=body.username,
            api_key=body.api_key,
        )
        check = svc.validate_credentials()
        if not check.success:
            raise HTTPException(status_code=400, detail="Invalid iCount credentials — please check your Company ID, username, and API key.")

    existing = (
        db.query(AccountingIntegration)
        .filter(
            AccountingIntegration.therapist_id == therapist.id,
            AccountingIntegration.provider == body.provider,
        )
        .first()
    )
    if existing:
        existing.access_token_enc = encrypt_token(body.api_key)
        existing.username_enc = encrypt_token(body.username)
        existing.company_id = body.company_id
        existing.is_active = True
        existing.updated_at = datetime.utcnow()
        integration = existing
    else:
        integration = AccountingIntegration(
            therapist_id=therapist.id,
            provider=body.provider,
            company_id=body.company_id,
            access_token_enc=encrypt_token(body.api_key),
            username_enc=encrypt_token(body.username),
            is_active=True,
        )
        db.add(integration)

    db.commit()
    db.refresh(integration)

    _log(db, therapist.id, "connect", "success",
         entity_type="integration", entity_id=integration.id)
    db.commit()

    logger.info(f"Therapist {therapist.id} connected {body.provider}")
    return integration


@router.delete("/disconnect")
def disconnect_accounting(
    provider: str = Query(...),
    therapist=Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    integration = (
        db.query(AccountingIntegration)
        .filter(
            AccountingIntegration.therapist_id == therapist.id,
            AccountingIntegration.provider == provider,
        )
        .first()
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    integration.is_active = False
    db.commit()

    _log(db, therapist.id, "disconnect", "success",
         entity_type="integration", entity_id=integration.id)
    db.commit()
    return {"ok": True}


@router.get("/status", response_model=Optional[AccountingIntegrationStatus])
def get_integration_status(
    therapist=Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    """Returns the active accounting integration for this therapist, or null."""
    return (
        db.query(AccountingIntegration)
        .filter(
            AccountingIntegration.therapist_id == therapist.id,
            AccountingIntegration.is_active == True,
        )
        .first()
    )


# ── Document endpoints ────────────────────────────────────────────────────────

@docs_router.get("/", response_model=List[AccountingDocumentOut])
def list_documents(
    doc_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    therapist=Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    q = db.query(AccountingDocument).filter(
        AccountingDocument.therapist_id == therapist.id
    )
    if doc_type:
        q = q.filter(AccountingDocument.doc_type == doc_type)
    if status:
        q = q.filter(AccountingDocument.status == status)
    return q.order_by(AccountingDocument.created_at.desc()).offset(offset).limit(limit).all()


@docs_router.get("/{doc_id}", response_model=AccountingDocumentOut)
def get_document(
    doc_id: uuid.UUID,
    therapist=Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    doc = db.query(AccountingDocument).filter(
        AccountingDocument.id == doc_id,
        AccountingDocument.therapist_id == therapist.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@docs_router.delete("/{doc_id}")
def delete_document(
    doc_id: uuid.UUID,
    therapist=Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    """Hard-delete an accounting document record (does not cancel in iCount)."""
    doc = db.query(AccountingDocument).filter(
        AccountingDocument.id == doc_id,
        AccountingDocument.therapist_id == therapist.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(doc)
    _log(db, therapist.id, "delete_document", "success",
         entity_type="document", entity_id=doc_id)
    db.commit()
    return {"ok": True}


@docs_router.post("/{doc_id}/resend")
def resend_document_email(
    doc_id: uuid.UUID,
    therapist=Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    """Resend the document email to the client via the provider or internal email."""
    doc = db.query(AccountingDocument).filter(
        AccountingDocument.id == doc_id,
        AccountingDocument.therapist_id == therapist.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status != DocumentStatus.ISSUED:
        raise HTTPException(status_code=400, detail="Can only resend issued documents")

    meta = doc.doc_metadata or {}
    client_email = meta.get("client_email", "")
    if not client_email:
        raise HTTPException(status_code=400, detail="No client email on record")

    service = get_accounting_service(therapist, db)
    if doc.external_id:
        result = service.resend_email(doc.external_id, client_email)
        if not result.success:
            # Fall back to internal email if provider resend fails
            _send_internal_email(doc, meta, therapist)
    else:
        _send_internal_email(doc, meta, therapist)

    _log(db, therapist.id, "resend_email",
         "success" if True else "failed",
         entity_type="document", entity_id=doc.id)
    db.commit()
    return {"ok": True}


def _send_internal_email(doc, meta: dict, therapist):
    try:
        send_invoice_email(
            client_email=meta.get("client_email", ""),
            client_name=meta.get("client_name", ""),
            therapist_name=therapist.name,
            invoice_number=meta.get("invoice_number", ""),
            amount=float(doc.amount),
            due_date=meta.get("due_date", ""),
            payment_link=doc.pdf_url,
            session_date=meta.get("session_date", ""),
            payment_instructions=therapist.payment_instructions,
        )
    except Exception as e:
        logger.warning(f"Internal email fallback failed for doc {doc.id}: {e}")


@docs_router.post("/{doc_id}/cancel")
def cancel_document(
    doc_id: uuid.UUID,
    issue_credit_note: bool = Query(False),
    therapist=Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    """
    Cancel a document. For Israel (immutable docs), creates a credit note instead.
    For US, marks the document as canceled directly.
    """
    doc = db.query(AccountingDocument).filter(
        AccountingDocument.id == doc_id,
        AccountingDocument.therapist_id == therapist.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status == DocumentStatus.CANCELED:
        raise HTTPException(status_code=400, detail="Document already canceled")

    service = get_accounting_service(therapist, db)
    country = getattr(therapist, "country", "US") or "US"
    meta = doc.doc_metadata or {}

    if country.upper() == "IL" or issue_credit_note:
        # Issue credit note for the original document
        payload = DocumentPayload(
            client_name=meta.get("client_name", ""),
            client_email=meta.get("client_email", ""),
            amount=float(doc.amount),
            currency=doc.currency,
            description=f"Credit note for document #{doc.external_id or doc.id}",
            invoice_number=meta.get("invoice_number", ""),
            original_external_id=doc.external_id,
        )
        result = service.create_credit_note(payload)
        if result.success:
            credit_doc = AccountingDocument(
                therapist_id=therapist.id,
                invoice_id=doc.invoice_id,
                parent_document_id=doc.id,
                doc_type=DocumentType.CREDIT_NOTE,
                external_id=result.external_id,
                pdf_url=result.pdf_url,
                status=DocumentStatus.ISSUED,
                amount=doc.amount,
                currency=doc.currency,
                doc_metadata=meta,
            )
            db.add(credit_doc)
            doc.status = DocumentStatus.CANCELED
            _log(db, therapist.id, "cancel_document", "success",
                 entity_type="document", entity_id=doc.id)
            db.commit()
            db.refresh(credit_doc)
            return {"ok": True, "credit_note_id": str(credit_doc.id)}
        else:
            _log(db, therapist.id, "cancel_document", "failed",
                 entity_type="document", entity_id=doc.id, error=result.error)
            db.commit()
            raise HTTPException(status_code=502, detail=result.error or "Credit note creation failed")
    else:
        result = service.cancel_document(doc.external_id or str(doc.id))
        doc.status = DocumentStatus.CANCELED
        _log(db, therapist.id, "cancel_document",
             "success" if result.success else "failed",
             entity_type="document", entity_id=doc.id,
             error=result.error if not result.success else None)
        db.commit()
        return {"ok": True}


@docs_router.post("/manual-receipt", response_model=AccountingDocumentOut)
def create_manual_receipt(
    body: ManualReceiptRequest,
    therapist=Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    """
    Create a receipt for a cash / offline payment.
    Useful when a client pays by check, bank transfer, or cash.
    """
    country = getattr(therapist, "country", "US") or "US"
    invoice_number = ""
    session_date = datetime.utcnow().strftime("%B %d, %Y")

    if body.invoice_id:
        inv = db.query(Invoice).filter(
            Invoice.id == body.invoice_id,
            Invoice.therapist_id == therapist.id,
        ).first()
        if inv:
            invoice_number = inv.invoice_number

    payload = DocumentPayload(
        client_name=body.client_name,
        client_email=body.client_email,
        amount=body.amount,
        currency=body.currency,
        description=body.description or f"Therapy Session — {session_date}",
        invoice_number=invoice_number,
        payment_method=body.payment_method,
        vat_rate=0.17 if country.upper() == "IL" else 0.0,
    )

    service = get_accounting_service(therapist, db)

    # Caller can override the document type; default is receipt_invoice for IL, receipt for US
    chosen = body.doc_type or (DocumentType.RECEIPT_INVOICE if country.upper() == "IL" else DocumentType.RECEIPT)
    dispatch = {
        DocumentType.INVOICE:         service.create_invoice,
        DocumentType.RECEIPT:         service.create_receipt,
        DocumentType.RECEIPT_INVOICE: service.create_receipt_invoice,
        DocumentType.CREDIT_NOTE:     service.create_credit_note,
    }
    create_fn = dispatch.get(chosen, service.create_receipt)
    doc_type = chosen
    result = create_fn(payload)

    vat = round(body.amount * 0.17 / 1.17, 2) if country.upper() == "IL" else None

    meta: dict = {
        "client_name": body.client_name,
        "client_email": body.client_email,
        "invoice_number": invoice_number,
        "payment_method": body.payment_method,
        "session_date": session_date,
    }
    if not result.success:
        if result.error:
            meta["provider_error"] = result.error
        if result.raw_response:
            meta["provider_raw_response"] = result.raw_response

    doc = AccountingDocument(
        therapist_id=therapist.id,
        invoice_id=body.invoice_id,
        doc_type=doc_type,
        external_id=result.external_id if result.success else None,
        pdf_url=result.pdf_url if result.success else None,
        status=DocumentStatus.ISSUED if result.success else DocumentStatus.FAILED,
        amount=body.amount,
        currency=body.currency,
        vat_amount=vat,
        doc_metadata=meta,
    )
    db.add(doc)
    db.flush()

    if not result.success:
        logger.warning(
            f"Manual receipt failed for therapist {therapist.id} — "
            f"provider: {type(service).__name__}, error: {result.error}"
        )
        _enqueue_retry(db, therapist.id, doc.id, "create_receipt", {
            "client_name": body.client_name,
            "client_email": body.client_email,
            "amount": body.amount,
            "currency": body.currency,
            "description": payload.description,
            "invoice_number": invoice_number,
            "payment_method": body.payment_method,
        })

    _log(db, therapist.id, "create_receipt",
         "success" if result.success else "failed",
         entity_type="document", entity_id=doc.id,
         error=result.error if not result.success else None)
    db.commit()
    db.refresh(doc)
    return doc


# ── Audit log ─────────────────────────────────────────────────────────────────

@docs_router.get("/audit-logs", response_model=List[AuditLogOut])
def list_audit_logs(
    limit: int = Query(50, le=200),
    offset: int = 0,
    therapist=Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    return (
        db.query(AuditLog)
        .filter(AuditLog.therapist_id == therapist.id)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


# ── Reports ───────────────────────────────────────────────────────────────────

@docs_router.get("/reports/monthly", response_model=MonthlyReportOut)
def monthly_report(
    year: int = Query(...),
    therapist=Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    from sqlalchemy import extract, cast, String

    rows = (
        db.query(
            func.to_char(AccountingDocument.created_at, "YYYY-MM").label("month"),
            func.sum(AccountingDocument.amount).label("total_amount"),
            func.coalesce(func.sum(AccountingDocument.vat_amount), 0).label("total_vat"),
            func.count(AccountingDocument.id).label("doc_count"),
            AccountingDocument.currency,
        )
        .filter(
            AccountingDocument.therapist_id == therapist.id,
            AccountingDocument.status == DocumentStatus.ISSUED,
            extract("year", AccountingDocument.created_at) == year,
        )
        .group_by(
            func.to_char(AccountingDocument.created_at, "YYYY-MM"),
            AccountingDocument.currency,
        )
        .order_by("month")
        .all()
    )

    report_rows = [
        MonthlyReportRow(
            month=r.month,
            total_amount=float(r.total_amount),
            total_vat=float(r.total_vat),
            document_count=r.doc_count,
            currency=r.currency,
        )
        for r in rows
    ]
    grand_total = sum(r.total_amount for r in report_rows)
    grand_vat = sum(r.total_vat for r in report_rows)

    return MonthlyReportOut(
        rows=report_rows,
        grand_total=grand_total,
        grand_vat=grand_vat,
    )


@docs_router.get("/reports/vat")
def vat_report(
    year: int = Query(...),
    month: int = Query(...),
    therapist=Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    """Israel-only VAT report for a specific month."""
    country = getattr(therapist, "country", "US") or "US"
    if country.upper() != "IL":
        raise HTTPException(status_code=403, detail="VAT report available for Israeli therapists only")

    from sqlalchemy import extract
    docs = (
        db.query(AccountingDocument)
        .filter(
            AccountingDocument.therapist_id == therapist.id,
            AccountingDocument.status == DocumentStatus.ISSUED,
            extract("year", AccountingDocument.created_at) == year,
            extract("month", AccountingDocument.created_at) == month,
        )
        .all()
    )

    total_before_vat = sum(float(d.amount) / 1.17 for d in docs)
    total_vat = sum(float(d.vat_amount or 0) for d in docs)
    total_with_vat = sum(float(d.amount) for d in docs)

    return {
        "year": year,
        "month": month,
        "document_count": len(docs),
        "total_before_vat": round(total_before_vat, 2),
        "total_vat": round(total_vat, 2),
        "total_with_vat": round(total_with_vat, 2),
        "currency": "ILS",
    }


@docs_router.get("/export/csv")
def export_csv(
    year: int = Query(...),
    therapist=Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    """Download all issued documents for a year as CSV."""
    from sqlalchemy import extract
    docs = (
        db.query(AccountingDocument)
        .filter(
            AccountingDocument.therapist_id == therapist.id,
            AccountingDocument.status == DocumentStatus.ISSUED,
            extract("year", AccountingDocument.created_at) == year,
        )
        .order_by(AccountingDocument.created_at)
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Type", "Document #", "Client", "Amount", "VAT", "Currency", "Status"])
    for d in docs:
        meta = d.doc_metadata or {}
        writer.writerow([
            d.created_at.strftime("%d/%m/%Y") if (getattr(therapist, "country", "US") or "US").upper() == "IL"
            else d.created_at.strftime("%m/%d/%Y"),
            d.doc_type,
            d.external_id or str(d.id),
            meta.get("client_name", ""),
            float(d.amount),
            float(d.vat_amount) if d.vat_amount else "",
            d.currency,
            d.status,
        ])

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),   # utf-8-sig = Excel-friendly BOM
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="documents_{year}.csv"'},
    )
