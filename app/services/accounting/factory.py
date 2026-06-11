"""
Factory: returns the correct accounting service for a therapist based on country.

For IL therapists: looks up their AccountingIntegration record, decrypts credentials,
returns an ICountAccountingService instance.

For US therapists (or fallback): returns a USAccountingService instance.
"""
import logging
from sqlalchemy.orm import Session

from .base import BaseAccountingService
from .israel import ICountAccountingService
from .green_invoice import GreenInvoiceAccountingService
from .us import USAccountingService
from app.core.security import decrypt_token

logger = logging.getLogger(__name__)

_IL_PROVIDERS = ("icount", "green_invoice")


def get_accounting_service(therapist, db: Session) -> BaseAccountingService:
    """
    Returns the accounting service appropriate for the therapist's country.
    Always returns a valid service — US is the safe default.
    """
    country = getattr(therapist, "country", "US") or "US"

    if country.upper() == "IL":
        return _build_israel_service(therapist, db)

    return USAccountingService()


def _build_israel_service(therapist, db: Session) -> BaseAccountingService:
    from app.models.accounting_integration import AccountingIntegration

    # Prefer whichever provider the therapist has active (icount or green_invoice)
    integration = (
        db.query(AccountingIntegration)
        .filter(
            AccountingIntegration.therapist_id == therapist.id,
            AccountingIntegration.provider.in_(_IL_PROVIDERS),
            AccountingIntegration.is_active == True,
        )
        .order_by(AccountingIntegration.updated_at.desc())
        .first()
    )

    if not integration:
        logger.warning(
            f"IL therapist {therapist.id} has no active accounting integration — "
            "falling back to US internal service"
        )
        return USAccountingService()

    try:
        api_key = decrypt_token(integration.access_token_enc) if integration.access_token_enc else ""
        username = decrypt_token(integration.username_enc) if integration.username_enc else ""

        if integration.provider == "green_invoice":
            # company_id stores the API key ID; access_token_enc stores the secret
            doc_type = getattr(integration, "green_invoice_doc_type", None) or "receipt"
            return GreenInvoiceAccountingService(
                api_key_id=integration.company_id or "",
                api_key_secret=api_key,
                default_doc_type=doc_type,
            )

        # Default: iCount
        return ICountAccountingService(
            company_id=integration.company_id or "",
            username=username,
            api_key=api_key,
        )
    except Exception as e:
        logger.error(f"Failed to build IL accounting service for therapist {therapist.id}: {e}")
        return USAccountingService()
