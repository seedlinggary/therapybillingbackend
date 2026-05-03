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
from .us import USAccountingService
from app.core.security import decrypt_token

logger = logging.getLogger(__name__)


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

    integration = (
        db.query(AccountingIntegration)
        .filter(
            AccountingIntegration.therapist_id == therapist.id,
            AccountingIntegration.provider == "icount",
            AccountingIntegration.is_active == True,
        )
        .first()
    )

    if not integration:
        logger.warning(
            f"IL therapist {therapist.id} has no active iCount integration — "
            "falling back to US internal service"
        )
        return USAccountingService()

    try:
        api_key = decrypt_token(integration.access_token_enc) if integration.access_token_enc else ""
        username = decrypt_token(integration.username_enc) if integration.username_enc else ""
        return ICountAccountingService(
            company_id=integration.company_id or "",
            username=username,
            api_key=api_key,
        )
    except Exception as e:
        logger.error(f"Failed to decrypt iCount credentials for therapist {therapist.id}: {e}")
        return USAccountingService()
