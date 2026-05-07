"""
Live exchange rate lookup via frankfurter.app (free, no key required).
Returns None on failure so callers can degrade gracefully.
"""
import logging
import requests

logger = logging.getLogger(__name__)
_BASE = "https://api.frankfurter.app/latest"


def get_rate(from_currency: str, to_currency: str) -> float | None:
    """Return how many units of `to_currency` equal one unit of `from_currency`."""
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()
    if from_currency == to_currency:
        return 1.0
    try:
        r = requests.get(
            _BASE,
            params={"from": from_currency, "to": to_currency},
            timeout=5,
        )
        r.raise_for_status()
        return float(r.json()["rates"][to_currency])
    except Exception as e:
        logger.warning(f"Exchange rate fetch {from_currency}→{to_currency} failed: {e}")
        return None


def build_conversion_note(amount: float, invoice_currency: str, other_currency: str) -> str | None:
    """
    Build a human-readable conversion note for an invoice.

    If the invoice is in USD and other is ILS:
        "Today's conversion from USD to ILS is 3.70 — $100.00 = ₪370.00"
    If the invoice is in ILS and other is USD:
        "Today's conversion from ILS to USD is 0.27 — ₪370.00 = $100.00"
    Returns None if the rate cannot be fetched.
    """
    invoice_currency = invoice_currency.upper()
    other_currency = other_currency.upper()
    if invoice_currency == other_currency:
        return None

    rate = get_rate(invoice_currency, other_currency)
    if rate is None:
        return None

    sym = {"USD": "$", "ILS": "₪", "EUR": "€", "GBP": "£"}
    from_sym = sym.get(invoice_currency, invoice_currency)
    to_sym = sym.get(other_currency, other_currency)

    converted = round(amount * rate, 2)
    return (
        f"Today's conversion from {invoice_currency} to {other_currency} is {rate:.4g} — "
        f"{from_sym}{amount:.2f} = {to_sym}{converted:.2f}"
    )
