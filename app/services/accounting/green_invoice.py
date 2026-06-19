"""
Green Invoice (חשבונית ירוקה / morning) accounting service.

API reference: https://www.greeninvoice.co.il/api-docs
Production:  https://api.greeninvoice.co.il/api/v1
Sandbox:     https://sandbox.d.greeninvoice.co.il/api/v1  (used when APP_ENV != "production")
Auth:        POST /account/token  →  { "id": api_key_id, "secret": api_key_secret }
           Response: { "token": "<JWT>" }
           All subsequent calls: Authorization: Bearer <JWT>

Document types (numeric):
  305 = Tax Invoice        (חשבונית מס)
  320 = Tax Invoice+Receipt (חשבונית מס קבלה)  ← most common
  330 = Credit Invoice     (חשבונית זיכוי)
  400 = Receipt            (קבלה)

VatType (document-level):
  0 = default (apply business default)
  1 = exempt  (VAT-exempt document)

IncomeVatType (per line item):
  1 = included  (price already includes VAT)
  2 = exempt

Payment types:
  1 = cash, 2 = check, 3 = credit card, 4 = bank transfer (EFT)

All amounts in ILS unless overridden.
"""
import json
import logging
from datetime import date as _date
from typing import Optional

import httpx

from .base import BaseAccountingService, AccountingResult, DocumentPayload
from app.config import settings

logger = logging.getLogger(__name__)

_GI_PROD    = "https://api.greeninvoice.co.il/api/v1"
_GI_SANDBOX = "https://sandbox.d.greeninvoice.co.il/api/v1"
GI_BASE = _GI_SANDBOX if settings.APP_ENV != "production" else _GI_PROD
IL_VAT_RATE = 0.18

# Numeric document type codes
_DOCTYPE = {
    "invoice":         305,
    "receipt_invoice": 320,
    "receipt":         400,
    "credit_note":     330,
}

# Payment method string → GI payment type code
_PAYMENT_TYPE = {
    "cash":          1,
    "check":         2,
    "credit_card":   3,
    "bank_transfer": 4,
    "online":        4,   # Stripe / online → treat as bank transfer (collected externally)
    "bit":           10,  # app payment
    "paybox":        10,  # app payment
    "paypal":        5,
}

# appType field required when payment type == 10 (app payment)
_APP_TYPE = {
    "bit":    1,
    "paybox": 3,
}


class GreenInvoiceAPIError(Exception):
    def __init__(self, message: str, raw: Optional[dict] = None,
                 http_status: Optional[int] = None, raw_text: Optional[str] = None):
        super().__init__(message)
        self.raw = raw
        self.http_status = http_status
        self.raw_text = raw_text

    def full_detail(self) -> str:
        parts = [str(self)]
        if self.http_status:
            parts.append(f"HTTP {self.http_status}")
        if self.raw:
            parts.append(f"response={json.dumps(self.raw, ensure_ascii=False)}")
        elif self.raw_text:
            parts.append(f"body={self.raw_text[:1000]}")
        return " | ".join(parts)


class GreenInvoiceAccountingService(BaseAccountingService):

    def __init__(self, api_key_id: str, api_key_secret: str,
                 default_doc_type: str = "receipt"):
        """
        default_doc_type: 'receipt' (400, safe default for all business types),
                          'receipt_invoice' (320), or 'invoice' (305, requires עוסק מורשה).
        The service will automatically fall back to 'receipt' (400) if the preferred type
        fails with error code 2403 (type not supported for this business).
        """
        self._key_id = api_key_id
        self._key_secret = api_key_secret
        self._default_doc_type = default_doc_type

    # ── Auth ─────────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        url = f"{GI_BASE}/account/token"
        try:
            resp = httpx.post(
                url,
                json={"id": self._key_id, "secret": self._key_secret},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30,
            )
        except httpx.RequestError as exc:
            raise GreenInvoiceAPIError(f"Green Invoice auth request error: {exc}")

        if resp.status_code >= 400:
            raise GreenInvoiceAPIError(
                "Green Invoice auth HTTP error",
                http_status=resp.status_code,
                raw_text=resp.text,
            )
        try:
            data = resp.json()
        except Exception:
            raise GreenInvoiceAPIError(
                "Green Invoice auth returned non-JSON",
                http_status=resp.status_code,
                raw_text=resp.text,
            )
        token = data.get("token")
        if not token:
            raise GreenInvoiceAPIError("Green Invoice auth: no token in response", raw=data)
        return token

    def _post(self, path: str, body: dict) -> dict:
        token = self._get_token()
        url = f"{GI_BASE}/{path.lstrip('/')}"

        safe = {k: ("***" if k in ("secret",) else v) for k, v in body.items()}
        print(f"\n[GreenInvoice] POST {url}\n[GreenInvoice] payload: {json.dumps(safe, ensure_ascii=False, indent=2)}\n", flush=True)

        try:
            resp = httpx.post(
                url,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=30,
            )
        except httpx.TimeoutException:
            raise GreenInvoiceAPIError(f"Green Invoice API timeout (path={path})")
        except httpx.ConnectError as exc:
            raise GreenInvoiceAPIError(f"Green Invoice connection error (path={path}): {exc}")
        except httpx.RequestError as exc:
            raise GreenInvoiceAPIError(f"Green Invoice request error (path={path}): {type(exc).__name__}: {exc}")

        raw_text = resp.text
        try:
            result = resp.json()
        except Exception:
            raise GreenInvoiceAPIError(
                "Green Invoice returned non-JSON",
                http_status=resp.status_code,
                raw_text=raw_text,
            )

        if resp.status_code >= 400:
            desc = result.get("description") or result.get("message") or raw_text[:500]
            raise GreenInvoiceAPIError(desc, raw=result, http_status=resp.status_code, raw_text=raw_text)

        return result

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        token = self._get_token()
        url = f"{GI_BASE}/{path.lstrip('/')}"
        try:
            resp = httpx.get(
                url,
                params=params,
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                timeout=30,
            )
        except httpx.RequestError as exc:
            raise GreenInvoiceAPIError(f"Green Invoice GET error: {exc}")
        if resp.status_code >= 400:
            raise GreenInvoiceAPIError(
                "Green Invoice GET HTTP error",
                http_status=resp.status_code,
                raw_text=resp.text,
            )
        return resp.json()

    # ── Document building ─────────────────────────────────────────────────────

    def _build_doc_payload(self, payload: DocumentPayload, doctype: int) -> dict:
        description = payload.description or "שירות"

        amount_ils = payload.amount
        if payload.currency == "USD" and getattr(payload, "exchange_rate", None):
            amount_ils = round(payload.amount * payload.exchange_rate, 2)

        effective_vat = payload.vat_rate if payload.vat_rate is not None else IL_VAT_RATE

        # GI expects the total price per line item inclusive of VAT when vatType=1 (included).
        # For exempt items use incomeVatType=2 and send the gross price as-is.
        income_vat_type = 2 if effective_vat == 0 else 1  # 1=included, 2=exempt
        # Document-level vatType: 0=default, 1=exempt
        doc_vat_type = 1 if effective_vat == 0 else 0

        income_item: dict = {
            "description": description,
            "price": amount_ils,
            "currency": "ILS",
            "quantity": 1,
            "vatType": income_vat_type,
        }

        pay_date = getattr(payload, "payment_date", None) or str(_date.today())
        method = (payload.payment_method or "cash").lower()
        payment_type = _PAYMENT_TYPE.get(method, 4)

        # Receipts default to sending email; invoices default to not sending
        _receipt_types = {_DOCTYPE["receipt"], _DOCTYPE["receipt_invoice"]}
        default_send = doctype in _receipt_types
        do_send = payload.send_email if payload.send_email is not None else default_send
        print(do_send, "!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        body: dict = {
            "type": doctype,
            "client": {
                "name": payload.client_name,
                "emails": [payload.client_email] if payload.client_email else [],
                "add": False,
            },
            "currency": "ILS",
            "vatType": doc_vat_type,
            "lang": "he",
            "signed": True,
            "sendByEmail": do_send,
            "rounding": False,
            "income": [income_item],
        }

        # Payment block — add for receipt types
        if doctype in (_DOCTYPE["receipt"], _DOCTYPE["receipt_invoice"]):
            payment_entry: dict = {
                "type": payment_type,
                "price": amount_ils,
                "currency": "ILS",
                "date": pay_date,
            }
            if method in _APP_TYPE:
                payment_entry["appType"] = _APP_TYPE[method]
            body["payment"] = [payment_entry]

        if payload.invoice_number:
            body["description"] = f"Invoice #{payload.invoice_number}"

        # Link receipt to original invoice
        if payload.original_external_id:
            body["linkedDocumentIds"] = [payload.original_external_id]

        return body

    def _create_document(self, doctype: int, payload: DocumentPayload,
                         extra: Optional[dict] = None) -> AccountingResult:
        """Issue a single GI document. No fallback logic — callers decide."""
        try:
            body = self._build_doc_payload(payload, doctype)
            if extra:
                body.update(extra)
            result = self._post("/documents", body)
            doc_id = str(result.get("id", ""))
            pdf_url = result.get("url", {}).get("origin")
            effective_vat = payload.vat_rate if payload.vat_rate is not None else IL_VAT_RATE
            vat = round(payload.amount * effective_vat / (1 + effective_vat), 2) if effective_vat > 0 else 0.0
            logger.info(f"Green Invoice document created: id={doc_id} doctype={doctype}")
            return AccountingResult(
                success=True,
                external_id=doc_id,
                pdf_url=pdf_url,
                vat_amount=vat,
                raw_response=result,
            )
        except GreenInvoiceAPIError as exc:
            detail = exc.full_detail()
            logger.error(f"Green Invoice create failed doctype={doctype}: {detail}")
            return AccountingResult(success=False, error=detail, raw_response=exc.raw)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            logger.exception(f"Green Invoice unexpected error doctype={doctype}: {detail}")
            return AccountingResult(success=False, error=detail)

    # ── Public interface ──────────────────────────────────────────────────────

    def create_invoice(self, payload: DocumentPayload) -> AccountingResult:
        """
        Issue חשבונית מס (305). No fallback — if it fails the retry worker retries
        the same type rather than silently downgrading to a different document.
        """
        return self._create_document(_DOCTYPE["invoice"], payload)

    def create_receipt(self, payload: DocumentPayload) -> AccountingResult:
        """
        Issue קבלה (400), typically linked to an existing חשבונית מס via
        payload.original_external_id. No fallback to receipt_invoice — that would
        produce a duplicate combined document alongside the existing 305.
        """
        return self._create_document(_DOCTYPE["receipt"], payload)

    def create_receipt_invoice(self, payload: DocumentPayload) -> AccountingResult:
        """
        Called when there is NO prior חשבונית מס for this invoice.
        Try קבלה (400) first; if that fails fall back to חשבונית מס קבלה (320).
        This is the only place a fallback is allowed, because no 305 exists yet
        so issuing a 320 cannot create a duplicate.
        """
        result = self._create_document(_DOCTYPE["receipt"], payload)
        if result.success:
            return result
        logger.warning(
            "create_receipt_invoice: קבלה (400) failed, falling back to "
            "חשבונית מס קבלה (320)"
        )
        return self._create_document(_DOCTYPE["receipt_invoice"], payload)

    def create_credit_note(self, payload: DocumentPayload) -> AccountingResult:
        return self._create_document(_DOCTYPE["credit_note"], payload)

    def cancel_document(self, external_id: str) -> AccountingResult:
        # Green Invoice has no cancel endpoint — cancel by issuing a credit note (type 330)
        try:
            body = {
                "type": _DOCTYPE["credit_note"],
                "client": {"add": False},
                "currency": "ILS",
                "lang": "he",
                "signed": True,
                "rounding": False,
                "linkedDocumentIds": [external_id],
            }
            result = self._post("/documents", body)
            credit_note_id = str(result.get("id", ""))
            logger.info(f"Green Invoice credit note created for cancellation: original={external_id} credit_note={credit_note_id}")
            return AccountingResult(success=True, external_id=credit_note_id, raw_response=result)
        except GreenInvoiceAPIError as exc:
            detail = exc.full_detail()
            logger.error(f"Green Invoice cancel failed #{external_id}: {detail}")
            return AccountingResult(success=False, error=detail, raw_response=exc.raw)
        except Exception as exc:
            return AccountingResult(success=False, error=f"{type(exc).__name__}: {exc}")

    def get_pdf(self, external_id: str) -> AccountingResult:
        try:
            result = self._get(f"/documents/{external_id}")
            pdf_url = result.get("url", {}).get("origin")
            return AccountingResult(success=True, external_id=external_id, pdf_url=pdf_url, raw_response=result)
        except GreenInvoiceAPIError as exc:
            detail = exc.full_detail()
            logger.error(f"Green Invoice get_pdf failed #{external_id}: {detail}")
            return AccountingResult(success=False, error=detail, raw_response=exc.raw)
        except Exception as exc:
            return AccountingResult(success=False, error=f"{type(exc).__name__}: {exc}")

    def resend_email(self, external_id: str, client_email: str) -> AccountingResult:
        try:
            result = self._post(f"/documents/{external_id}/email", {"emails": [client_email]})
            return AccountingResult(success=True, external_id=external_id, raw_response=result)
        except GreenInvoiceAPIError as exc:
            detail = exc.full_detail()
            logger.error(f"Green Invoice resend_email failed #{external_id}: {detail}")
            return AccountingResult(success=False, error=detail, raw_response=exc.raw)
        except Exception as exc:
            return AccountingResult(success=False, error=f"{type(exc).__name__}: {exc}")

    def validate_credentials(self) -> AccountingResult:
        """Validate by successfully obtaining a JWT token."""
        print(
            f"\n[GreenInvoice VALIDATE]"
            f"\n  key_id = {self._key_id[:4]}*** (len={len(self._key_id)})"
            f"\n  secret = {self._key_secret[:2]}*** (len={len(self._key_secret)})",
            flush=True,
        )
        try:
            token = self._get_token()
            if token:
                return AccountingResult(success=True)
            return AccountingResult(success=False, error="No token returned")
        except GreenInvoiceAPIError as exc:
            return AccountingResult(success=False, error=exc.full_detail(), raw_response=exc.raw)
        except Exception as exc:
            return AccountingResult(success=False, error=f"{type(exc).__name__}: {exc}")
