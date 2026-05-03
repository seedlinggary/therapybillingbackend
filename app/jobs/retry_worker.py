"""
Accounting retry worker — processes failed accounting_retry_jobs.

Exponential backoff delays (minutes): 1, 5, 15, 60, 240, 1440
Max 6 attempts; marks job 'failed' permanently after exhausting retries.
Logs every attempt to accounting_audit_logs.

Called by APScheduler every 5 minutes.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.accounting_document import AccountingDocument, DocumentStatus
from app.models.audit_log import AuditLog
from app.models.retry_job import RetryJob
from app.models.therapist import Therapist
from app.services.accounting import get_accounting_service
from app.services.accounting.base import DocumentPayload

logger = logging.getLogger(__name__)

# Backoff delay in minutes for attempt index 0..5
_BACKOFF_MINUTES = [1, 5, 15, 60, 240, 1440]


def _next_delay(attempt: int) -> timedelta:
    idx = min(attempt, len(_BACKOFF_MINUTES) - 1)
    return timedelta(minutes=_BACKOFF_MINUTES[idx])


def run_retry_worker():
    """Entry point — called every 5 minutes by APScheduler."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        due_jobs = (
            db.query(RetryJob)
            .filter(
                RetryJob.status.in_(["pending", "retrying"]),
                RetryJob.next_attempt_at <= now,
            )
            .order_by(RetryJob.next_attempt_at)
            .limit(50)
            .all()
        )

        if not due_jobs:
            return

        logger.info(f"Retry worker: processing {len(due_jobs)} jobs")
        for job in due_jobs:
            _process_job(db, job)

    finally:
        db.close()


def _process_job(db: Session, job: RetryJob):
    therapist = db.query(Therapist).filter(Therapist.id == job.therapist_id).first()
    if not therapist:
        job.status = "failed"
        job.last_error = "Therapist not found"
        db.commit()
        return

    job.attempts += 1
    job.status = "retrying"
    db.flush()

    try:
        result = _execute_job(job, therapist, db)
        success = result.success
        error = result.error
    except Exception as e:
        success = False
        error = str(e)
        logger.exception(f"Retry job {job.id} raised an exception: {e}")

    if success:
        job.status = "succeeded"
        job.last_error = None
        # Update the associated document to ISSUED
        if job.document_id:
            doc = db.query(AccountingDocument).filter(
                AccountingDocument.id == job.document_id
            ).first()
            if doc:
                from app.services.accounting.base import AccountingResult
                # result is available in the local scope via the try block
                doc.status = DocumentStatus.ISSUED
                doc.external_id = getattr(result, 'external_id', None) or doc.external_id
                doc.pdf_url = getattr(result, 'pdf_url', None) or doc.pdf_url
                doc.updated_at = datetime.utcnow()
        _audit(db, job, "retry", "success")
    else:
        job.last_error = error
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            if job.document_id:
                doc = db.query(AccountingDocument).filter(
                    AccountingDocument.id == job.document_id
                ).first()
                if doc:
                    doc.status = DocumentStatus.FAILED
            _audit(db, job, "retry", "failed", error=error)
            logger.warning(f"Retry job {job.id} permanently failed after {job.attempts} attempts: {error}")
        else:
            job.status = "pending"
            job.next_attempt_at = datetime.utcnow() + _next_delay(job.attempts)
            _audit(db, job, "retry", "failed", error=error)
            logger.info(f"Retry job {job.id} attempt {job.attempts} failed — next at {job.next_attempt_at}")

    job.updated_at = datetime.utcnow()
    db.commit()


def _execute_job(job: RetryJob, therapist, db: Session):
    """Dispatch job to the appropriate service method."""
    p = job.payload
    payload = DocumentPayload(
        client_name=p.get("client_name", ""),
        client_email=p.get("client_email", ""),
        amount=float(p.get("amount", 0)),
        currency=p.get("currency", "USD"),
        description=p.get("description", ""),
        invoice_number=p.get("invoice_number", ""),
        payment_method=p.get("payment_method", "online"),
        original_external_id=p.get("original_external_id"),
    )

    service = get_accounting_service(therapist, db)

    dispatch = {
        "create_receipt": service.create_receipt,
        "create_invoice": service.create_invoice,
        "create_receipt_invoice": service.create_receipt_invoice,
        "create_credit_note": service.create_credit_note,
    }

    fn = dispatch.get(job.job_type)
    if not fn:
        from app.services.accounting.base import AccountingResult
        return AccountingResult(success=False, error=f"Unknown job_type: {job.job_type}")

    return fn(payload)


def _audit(db: Session, job: RetryJob, action: str, status: str, error: str = None):
    db.add(AuditLog(
        therapist_id=job.therapist_id,
        action=action,
        status=status,
        entity_type="document",
        entity_id=job.document_id,
        error_message=error,
        log_metadata={"job_id": str(job.id), "attempt": job.attempts, "job_type": job.job_type},
    ))
