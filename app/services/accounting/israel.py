"""
Israel accounting service — integrates with iCount (חשבונית ירוקה).

iCount API reference: https://api.icount.co.il/docs
Base URL: https://api.icount.co.il/api/v3.php
Auth:     JSON body fields: cid, user, pass
Content-Type: application/json

Document type strings (doctype param):
  invoice         = Tax Invoice              (חשבונית מס)
  receipt_invoice = Receipt Invoice          (חשבונית מס קבלה)   ← most common
  receipt         = Receipt                  (קבלה)
  credit_note     = Credit Note              (חשבונית מס זיכוי)

All amounts are in ILS (₪) unless overridden.
VAT rate in Israel: 18% (raised from 17% on Jan 1, 2025).
"""
import json
import logging
from typing import Optional

import httpx

from .base import BaseAccountingService, AccountingResult, DocumentPayload

logger = logging.getLogger(__name__)

ICOUNT_API_URL = "https://api.icount.co.il/api/v3.php"
IL_VAT_RATE = 0.18  # Israel raised VAT from 17% to 18% on Jan 1, 2025

_DOCTYPE = {
    "invoice":         "invoice",         # חשבונית מס
    "receipt_invoice": "invrec",          # חשבונית מס קבלה (most common for IL)
    "receipt":         "receipt",         # קבלה
    "credit_note":     "credit_note",     # חשבונית מס זיכוי
}

# iCount adds VAT on top of unitprice for these types → we must send the pre-VAT price.
# Derived from _DOCTYPE values so it stays in sync if the strings ever change.
_VAT_DOCTYPE_VALUES = {_DOCTYPE["invoice"], _DOCTYPE["receipt_invoice"], _DOCTYPE["credit_note"]}


class ICountAPIError(Exception):
    """Raised when iCount returns a non-success response or the request fails."""

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


class ICountAccountingService(BaseAccountingService):

    def __init__(self, company_id: str, username: str, api_key: str):
        self._cid = company_id
        self._user = username
        self._pass = api_key

    def _auth_fields(self) -> dict:
        return {"cid": self._cid, "user": self._user, "pass": self._pass}

    def _post(self, action: str, extra: dict) -> dict:
        """
        POST JSON to iCount and return the parsed response on success.

        iCount v3 routes by URL path:  "doc.create" → /api/v3.php/doc/create
        Body is JSON (Content-Type: application/json).
        """
        path = action.replace(".", "/")
        url = f"{ICOUNT_API_URL}/{path}"
        payload = {**self._auth_fields(), **extra}

        # Debug: show what we're sending (mask credentials)
        safe = {k: ("***" if k in ("pass", "user") else v) for k, v in payload.items()}
        print(f"\n[iCount] POST {url}\n[iCount] payload: {json.dumps(safe, ensure_ascii=False, indent=2)}\n", flush=True)

        try:
            response = httpx.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30,
            )
        except httpx.TimeoutException:
            raise ICountAPIError(f"iCount API timeout — no response within 30s (action={action})")
        except httpx.ConnectError as exc:
            raise ICountAPIError(f"iCount API connection error (action={action}): {exc}")
        except httpx.RequestError as exc:
            raise ICountAPIError(f"iCount API request error (action={action}): {type(exc).__name__}: {exc}")

        raw_text = response.text

        try:
            result = response.json()
        except Exception:
            raise ICountAPIError(
                "iCount returned non-JSON body",
                http_status=response.status_code,
                raw_text=raw_text,
            )

        if response.status_code >= 400:
            raise ICountAPIError(
                "iCount HTTP error",
                raw=result,
                http_status=response.status_code,
                raw_text=raw_text,
            )

        app_ok = result.get("status") == 1 or result.get("status") is True
        if not app_ok:
            error_fields = {}
            for key in ("error_description", "reason", "error_message",
                        "error_code", "developer_message", "description",
                        "message", "error"):
                val = result.get(key)
                if val:
                    error_fields[key] = val

            if error_fields:
                primary = (
                    error_fields.get("error_description")
                    or error_fields.get("error_message")
                    or error_fields.get("message")
                    or error_fields.get("reason")
                    or str(error_fields)
                )
            else:
                primary = "iCount returned status=false with no error message"

            raise ICountAPIError(primary, raw=result, http_status=response.status_code, raw_text=raw_text)

        return result

    def _build_doc_payload(self, payload: DocumentPayload, doctype: str) -> dict:
        description = payload.description or "שירות"

        # For USD invoices from IL therapists, convert to ILS using exchange rate.
        # iCount always operates in ILS internally.
        amount_ils = payload.amount
        if payload.currency == "USD" and getattr(payload, "exchange_rate", None):
            amount_ils = round(payload.amount * payload.exchange_rate, 2)

        # For VAT invoice types iCount adds 18% on top of unitprice → send pre-VAT.
        # For plain receipt iCount treats unitprice as the gross total → send gross.
        if doctype in _VAT_DOCTYPE_VALUES:
            unitprice = round(amount_ils / (1 + IL_VAT_RATE), 2)
        else:
            unitprice = amount_ils

        body: dict = {
            "doctype":         doctype,
            "client_name":     payload.client_name,
            "email":           payload.client_email,
            "currency_code":   "ILS",
            "lang":            "he",
            "send_email":      1,
            "email_to_client": 1,
            "items": [
                {
                    "description": description,
                    "unitprice":   unitprice,
                    "quantity":    1,
                }
            ],
        }

        # Payment section — only relevant for receipt / receipt_invoice docs
        method = (payload.payment_method or "cash").lower()
        if method == "cash":
            body["cash"] = {"sum": amount_ils}
        elif method == "check":
            body["check"] = {"sum": amount_ils}
        elif method == "bank_transfer":
            body["bank_transfer"] = {"sum": amount_ils}
        # "online" (Stripe) — no payment block; iCount treats it as already collected

        if payload.invoice_number:
            body["description"] = f"Invoice #{payload.invoice_number}"

        # Link receipt/credit-note to the original iCount invoice docnum
        if payload.original_external_id:
            body["origin_docnum"] = payload.original_external_id

        return body

    @staticmethod
    def _payment_type_code(method: str) -> int:
        return {"online": 4, "cash": 1, "check": 2, "bank_transfer": 3}.get(method, 4)

    def _create_document(self, doctype: str, payload: DocumentPayload,
                         extra: Optional[dict] = None) -> AccountingResult:
        try:
            body = self._build_doc_payload(payload, doctype)
            if extra:
                body.update(extra)
            result = self._post("doc.create", body)
            doc_number = str(result.get("docnum", ""))
            pdf_url = result.get("doc_url") or result.get("pdf_url")
            vat = round(payload.amount * IL_VAT_RATE / (1 + IL_VAT_RATE), 2)
            logger.info(f"iCount document created: #{doc_number} doctype={doctype}")
            return AccountingResult(
                success=True,
                external_id=doc_number,
                pdf_url=pdf_url,
                vat_amount=vat,
                raw_response=result,
            )
        except ICountAPIError as exc:
            detail = exc.full_detail()
            logger.error(f"iCount doc.create failed doctype={doctype}: {detail}")
            return AccountingResult(success=False, error=detail, raw_response=exc.raw)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            logger.exception(f"iCount unexpected error doctype={doctype}: {detail}")
            return AccountingResult(success=False, error=detail)

    # ── Public interface ──────────────────────────────────────────────────────

    def create_invoice(self, payload: DocumentPayload) -> AccountingResult:
        return self._create_document(_DOCTYPE["invoice"], payload)

    def create_receipt(self, payload: DocumentPayload) -> AccountingResult:
        return self._create_document(_DOCTYPE["receipt"], payload)

    def create_receipt_invoice(self, payload: DocumentPayload) -> AccountingResult:
        return self._create_document(_DOCTYPE["receipt_invoice"], payload)

    def create_credit_note(self, payload: DocumentPayload) -> AccountingResult:
        extra = {}
        if payload.original_external_id:
            extra["origin_docnum"] = payload.original_external_id
        return self._create_document(_DOCTYPE["credit_note"], payload, extra)

    def cancel_document(self, external_id: str) -> AccountingResult:
        try:
            result = self._post("doc.cancel", {"docnum": external_id})
            logger.info(f"iCount document cancelled: #{external_id}")
            return AccountingResult(success=True, external_id=external_id, raw_response=result)
        except ICountAPIError as exc:
            detail = exc.full_detail()
            logger.error(f"iCount doc.cancel failed #{external_id}: {detail}")
            return AccountingResult(success=False, error=detail, raw_response=exc.raw)
        except Exception as exc:
            return AccountingResult(success=False, error=f"{type(exc).__name__}: {exc}")

    def get_pdf(self, external_id: str) -> AccountingResult:
        try:
            result = self._post("doc.pdf_url", {"docnum": external_id})
            return AccountingResult(
                success=True,
                external_id=external_id,
                pdf_url=result.get("pdf_url"),
                raw_response=result,
            )
        except ICountAPIError as exc:
            detail = exc.full_detail()
            logger.error(f"iCount doc.pdf_url failed #{external_id}: {detail}")
            return AccountingResult(success=False, error=detail, raw_response=exc.raw)
        except Exception as exc:
            return AccountingResult(success=False, error=f"{type(exc).__name__}: {exc}")

    def resend_email(self, external_id: str, client_email: str) -> AccountingResult:
        try:
            result = self._post("doc.send_email", {"docnum": external_id, "email": client_email})
            return AccountingResult(success=True, external_id=external_id, raw_response=result)
        except ICountAPIError as exc:
            detail = exc.full_detail()
            logger.error(f"iCount resend_email failed #{external_id}: {detail}")
            return AccountingResult(success=False, error=detail, raw_response=exc.raw)
        except Exception as exc:
            return AccountingResult(success=False, error=f"{type(exc).__name__}: {exc}")
