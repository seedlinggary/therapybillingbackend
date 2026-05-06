"""
Invoices — CRUD, PDF download, Stripe checkout, bill-now, delete, mark-paid.
"""
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload
import stripe

from app.database import get_db
from app.core.deps import get_current_therapist, get_current_client
from app.models.therapist import Therapist
from app.models.client import Client
from app.models.invoice import Invoice, InvoiceStatus
from app.models.invoice_item import InvoiceItem
from app.models.appointment import Appointment, AppointmentStatus
from app.models.therapist_client import TherapistClient
from app.models.payment import Payment
from app.schemas.invoice import InvoiceResponse, InvoiceItemResponse, InvoiceCreate
from app.services.stripe_service import generate_invoice_number
from app.services.pdf_service import generate_invoice_pdf
from app.services.email_service import send_invoice_email
from app.services.accounting.trigger import issue_accounting_receipt, issue_accounting_invoice
from app.services.payment import get_payment_provider
from app.services.payment.base import PaymentProvider, PaymentSessionRequest
from app.models.payme_metadata import PayMePaymentMetadata
from app.config import settings

router = APIRouter(tags=["invoices"])


def _item_response(item: InvoiceItem) -> InvoiceItemResponse:
    return InvoiceItemResponse(
        id=item.id,
        appointment_id=item.appointment_id,
        amount=float(item.amount),
        description=item.description,
        appointment_start=item.appointment.start_time if item.appointment else None,
    )


def _build_response(invoice: Invoice) -> InvoiceResponse:
    # Build items list; fall back to synthetic item for old invoices without items
    items = [_item_response(it) for it in (invoice.items or [])]
    if not items and invoice.appointment:
        items = [InvoiceItemResponse(
            id=invoice.id,  # reuse invoice id as placeholder
            appointment_id=invoice.appointment_id,
            amount=float(invoice.amount),
            description="Therapy Session",
            appointment_start=invoice.appointment.start_time,
        )]

    first_start = items[0].appointment_start if items else None

    return InvoiceResponse(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        therapist_id=invoice.therapist_id,
        therapist_name=invoice.therapist.name if invoice.therapist else None,
        client_id=invoice.client_id,
        client_name=invoice.client.name if invoice.client else None,
        appointment_id=invoice.appointment_id,
        appointment_start=first_start,
        items=items,
        amount=float(invoice.amount),
        currency=getattr(invoice, "currency", None) or "USD",
        status=invoice.status,
        due_date=invoice.due_date,
        paid_at=invoice.paid_at,
        payment_provider=getattr(invoice, "payment_provider", None) or "stripe",
        payment_link=invoice.payment_link,
        stripe_payment_link=invoice.stripe_payment_link,
        created_at=invoice.created_at,
    )


def _load_invoice(db: Session):
    return db.query(Invoice).options(
        joinedload(Invoice.therapist),
        joinedload(Invoice.client),
        joinedload(Invoice.appointment),
        joinedload(Invoice.items).joinedload(InvoiceItem.appointment),
    )


def _resolve_amount(appt: Appointment, rel: TherapistClient, therapist: Therapist) -> float:
    if appt.override_price is not None:
        return float(appt.override_price)
    if rel and rel.default_session_price:
        return float(rel.default_session_price)
    if therapist and getattr(therapist, "default_session_price", None):
        return float(therapist.default_session_price)
    return 0.0



def _attach_payment_session(db: Session, invoice: Invoice, therapist: Therapist):
    """
    Create a payment session with whichever provider the therapist uses.
    Silently skips if credentials aren't configured.
    For PayMe, also writes a PayMePaymentMetadata row so the webhook handler
    can resolve the invoice from the payme_sale_id.
    """
    provider_name = getattr(therapist, "payment_provider", None) or PaymentProvider.STRIPE
    invoice.payment_provider = provider_name

    try:
        provider = get_payment_provider(therapist)
        req = PaymentSessionRequest(
            invoice_id=str(invoice.id),
            therapist_id=str(therapist.id),
            client_id=str(invoice.client_id),
            amount=float(invoice.amount),
            currency=getattr(invoice, "currency", "USD"),
            invoice_number=invoice.invoice_number,
            success_url=f"{settings.FRONTEND_URL}/client/invoices?paid=true&invoice_id={invoice.id}",
            cancel_url=f"{settings.FRONTEND_URL}/client/invoices",
            description=f"Therapy Session — Invoice #{invoice.invoice_number}",
            metadata={
                "webhook_url": f"{settings.BACKEND_URL}/webhooks/payme"
                if provider_name == PaymentProvider.PAYME else "",
            },
        )
        session = provider.create_payment_session(req)

        if provider_name == PaymentProvider.PAYME:
            invoice.payme_sale_id    = session.external_id
            invoice.payme_payment_link = session.payment_url
            # Store metadata mapping so webhook can find this invoice
            db.add(PayMePaymentMetadata(
                payme_sale_id=session.external_id,
                invoice_id=invoice.id,
                therapist_id=therapist.id,
                client_id=invoice.client_id,
                extra_data={
                    "invoice_id":   str(invoice.id),
                    "therapist_id": str(therapist.id),
                    "client_id":    str(invoice.client_id),
                },
            ))
        else:
            invoice.stripe_checkout_session_id = session.external_id
            invoice.stripe_payment_link        = session.payment_url

    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).warning(f"Payment session creation failed for invoice {invoice.id}: {e}")


# ─── Therapist: create invoice manually ───────────────────────────────────────

@router.post("/therapist/invoices", response_model=InvoiceResponse, status_code=201)
def create_invoice(
    data: InvoiceCreate,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    appt = db.query(Appointment).filter(
        Appointment.id == data.appointment_id,
        Appointment.therapist_id == therapist.id,
    ).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != AppointmentStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Can only invoice completed appointments")
    if appt.billed:
        raise HTTPException(status_code=409, detail="Appointment already billed")

    rel = db.query(TherapistClient).filter(
        TherapistClient.therapist_id == therapist.id,
        TherapistClient.client_id == appt.client_id,
    ).first()
    amount = _resolve_amount(appt, rel, therapist)
    due_date = data.due_date or datetime.utcnow() + timedelta(days=30)
    currency = getattr(therapist, "default_currency", None) or "USD"

    invoice = Invoice(
        therapist_id=therapist.id, client_id=appt.client_id,
        appointment_id=appt.id,
        invoice_number=generate_invoice_number(),
        amount=amount, status=InvoiceStatus.UNPAID,
        due_date=due_date, notes=data.notes,
        currency=currency,
    )
    db.add(invoice)
    db.flush()

    db.add(InvoiceItem(
        invoice_id=invoice.id, appointment_id=appt.id,
        amount=amount,
        description=f"Therapy Session — {appt.start_time.strftime('%B %d, %Y')}",
    ))

    _attach_payment_session(db, invoice, therapist)

    appt.billed = True
    db.commit()
    db.refresh(invoice)

    try:
        send_invoice_email(
            client_email=appt.client.email, client_name=appt.client.name,
            therapist_name=therapist.name,
            invoice_number=invoice.invoice_number, amount=amount,
            due_date=due_date.strftime("%B %d, %Y"),
            payment_link=invoice.payment_link,
            session_date=appt.start_time.strftime("%B %d, %Y"),
            payment_instructions=therapist.payment_instructions,
            currency=currency,
        )
    except Exception:
        pass

    issue_accounting_invoice(invoice, therapist, db)

    return _build_response(_load_invoice(db).filter(Invoice.id == invoice.id).first())


# ─── Bill Now (immediate single-appointment invoice) ──────────────────────────

@router.post("/therapist/appointments/{appointment_id}/bill-now",
             response_model=InvoiceResponse, status_code=201)
def bill_now(
    appointment_id: str,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    appt = db.query(Appointment).options(
        joinedload(Appointment.client)
    ).filter(
        Appointment.id == appointment_id,
        Appointment.therapist_id == therapist.id,
    ).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != AppointmentStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Can only bill completed appointments")
    if appt.billed:
        raise HTTPException(status_code=409, detail="Appointment already billed")

    rel = db.query(TherapistClient).filter(
        TherapistClient.therapist_id == therapist.id,
        TherapistClient.client_id == appt.client_id,
    ).first()
    amount = _resolve_amount(appt, rel, therapist)
    due_date = datetime.utcnow() + timedelta(days=30)
    currency = getattr(therapist, "default_currency", None) or "USD"

    invoice = Invoice(
        therapist_id=therapist.id, client_id=appt.client_id,
        appointment_id=appt.id,
        invoice_number=generate_invoice_number(),
        amount=amount, status=InvoiceStatus.UNPAID,
        due_date=due_date,
        currency=currency,
    )
    db.add(invoice)
    db.flush()

    db.add(InvoiceItem(
        invoice_id=invoice.id, appointment_id=appt.id,
        amount=amount,
        description=f"Therapy Session — {appt.start_time.strftime('%B %d, %Y')}",
    ))

    _attach_payment_session(db, invoice, therapist)

    appt.billed = True
    db.commit()
    db.refresh(invoice)

    try:
        send_invoice_email(
            client_email=appt.client.email, client_name=appt.client.name,
            therapist_name=therapist.name,
            invoice_number=invoice.invoice_number, amount=amount,
            due_date=due_date.strftime("%B %d, %Y"),
            payment_link=invoice.payment_link,
            session_date=appt.start_time.strftime("%B %d, %Y"),
            payment_instructions=therapist.payment_instructions,
            currency=currency,
        )
    except Exception:
        pass

    issue_accounting_invoice(invoice, therapist, db)

    return _build_response(_load_invoice(db).filter(Invoice.id == invoice.id).first())


# ─── Therapist: list / get ─────────────────────────────────────────────────────

@router.get("/therapist/invoices", response_model=List[InvoiceResponse])
def list_therapist_invoices(
    status: Optional[str] = None,
    client_id: Optional[str] = None,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    q = _load_invoice(db).filter(Invoice.therapist_id == therapist.id)
    if status:
        q = q.filter(Invoice.status == status)
    if client_id:
        q = q.filter(Invoice.client_id == client_id)
    return [_build_response(i) for i in q.order_by(Invoice.created_at.desc()).all()]


@router.get("/therapist/invoices/{invoice_id}", response_model=InvoiceResponse)
def get_therapist_invoice(
    invoice_id: str,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    invoice = _load_invoice(db).filter(
        Invoice.id == invoice_id, Invoice.therapist_id == therapist.id,
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _build_response(invoice)


# ─── Therapist: delete unpaid invoice ─────────────────────────────────────────

@router.delete("/therapist/invoices/{invoice_id}", status_code=204)
def delete_invoice(
    invoice_id: str,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    invoice = _load_invoice(db).filter(
        Invoice.id == invoice_id, Invoice.therapist_id == therapist.id,
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != InvoiceStatus.UNPAID:
        raise HTTPException(status_code=400, detail="Only unpaid invoices can be deleted")

    # Release all linked appointments back to unbilled
    appt_ids = [item.appointment_id for item in invoice.items]
    if not appt_ids and invoice.appointment_id:
        appt_ids = [invoice.appointment_id]

    db.query(Appointment).filter(Appointment.id.in_(appt_ids)).update(
        {"billed": False}, synchronize_session=False
    )

    db.delete(invoice)
    db.commit()


# ─── Therapist: verify payment with Stripe ────────────────────────────────────

@router.post("/therapist/invoices/{invoice_id}/verify-stripe-payment", response_model=InvoiceResponse)
def verify_stripe_payment(
    invoice_id: str,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    """
    Pulls the live payment status from Stripe and marks the invoice as paid if confirmed.
    Does not depend on webhooks — therapist can call this any time after the client pays.
    """
    invoice = _load_invoice(db).filter(
        Invoice.id == invoice_id,
        Invoice.therapist_id == therapist.id,
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.status == InvoiceStatus.PAID:
        return _build_response(invoice)

    if not invoice.stripe_checkout_session_id:
        raise HTTPException(status_code=400, detail="No Stripe checkout session associated with this invoice")

    if not therapist.stripe_account_id:
        raise HTTPException(status_code=400, detail="Stripe account not connected")

    try:
        session = stripe.checkout.Session.retrieve(
            invoice.stripe_checkout_session_id,
            stripe_account=therapist.stripe_account_id,
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=f"Could not reach Stripe: {e}")

    if session.payment_status != "paid":
        raise HTTPException(status_code=400, detail=f"Payment not completed in Stripe (status: {session.payment_status})")

    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = datetime.utcnow()
    if session.payment_intent:
        invoice.stripe_payment_intent_id = str(session.payment_intent)
        existing = db.query(Payment).filter(
            Payment.stripe_payment_intent_id == str(session.payment_intent)
        ).first()
        if not existing:
            db.add(Payment(
                invoice_id=invoice.id,
                amount=invoice.amount,
                stripe_payment_intent_id=str(session.payment_intent),
                status="succeeded",
                paid_at=datetime.utcnow(),
            ))

    db.commit()
    issue_accounting_receipt(invoice, db, payment_method="online")
    return _build_response(_load_invoice(db).filter(Invoice.id == invoice_id).first())


# ─── Therapist: mark paid manually ────────────────────────────────────────────

@router.post("/therapist/invoices/{invoice_id}/mark-paid", response_model=InvoiceResponse)
def mark_invoice_paid(
    invoice_id: str,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    invoice = _load_invoice(db).filter(
        Invoice.id == invoice_id, Invoice.therapist_id == therapist.id,
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == InvoiceStatus.PAID:
        raise HTTPException(status_code=400, detail="Invoice already paid")
    if invoice.status == InvoiceStatus.VOID:
        raise HTTPException(status_code=400, detail="Cannot mark a voided invoice as paid")

    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = datetime.utcnow()
    db.commit()
    db.refresh(invoice)
    issue_accounting_receipt(invoice, db, payment_method="cash")
    return _build_response(invoice)


# ─── Therapist: void / resend ──────────────────────────────────────────────────

@router.post("/therapist/invoices/{invoice_id}/void", response_model=InvoiceResponse)
def void_invoice(
    invoice_id: str,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    invoice = _load_invoice(db).filter(
        Invoice.id == invoice_id, Invoice.therapist_id == therapist.id,
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == InvoiceStatus.PAID:
        raise HTTPException(status_code=400, detail="Cannot void a paid invoice")

    invoice.status = InvoiceStatus.VOID

    # Release linked appointments so they can be re-billed or canceled
    appt_ids = [item.appointment_id for item in invoice.items]
    if not appt_ids and invoice.appointment_id:
        appt_ids = [invoice.appointment_id]
    if appt_ids:
        db.query(Appointment).filter(Appointment.id.in_(appt_ids)).update(
            {"billed": False}, synchronize_session=False
        )

    db.commit()
    db.refresh(invoice)
    return _build_response(invoice)


@router.post("/therapist/invoices/{invoice_id}/resend", status_code=200)
def resend_invoice_email(
    invoice_id: str,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    invoice = _load_invoice(db).filter(
        Invoice.id == invoice_id, Invoice.therapist_id == therapist.id,
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    first_date = invoice.items[0].appointment.start_time if invoice.items else (
        invoice.appointment.start_time if invoice.appointment else None
    )
    send_invoice_email(
        client_email=invoice.client.email, client_name=invoice.client.name,
        therapist_name=therapist.name,
        invoice_number=invoice.invoice_number, amount=float(invoice.amount),
        due_date=invoice.due_date.strftime("%B %d, %Y"),
        payment_link=invoice.stripe_payment_link,
        session_date=first_date.strftime("%B %d, %Y") if first_date else "N/A",
        payment_instructions=therapist.payment_instructions,
    )
    return {"message": "Invoice email resent"}


# ─── Client endpoints ─────────────────────────────────────────────────────────

@router.get("/client/invoices", response_model=List[InvoiceResponse])
def list_client_invoices(
    status: Optional[str] = None,
    therapist_id: Optional[str] = None,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    q = _load_invoice(db).filter(Invoice.client_id == client.id)
    if status:
        q = q.filter(Invoice.status == status)
    if therapist_id:
        q = q.filter(Invoice.therapist_id == therapist_id)
    return [_build_response(i) for i in q.order_by(Invoice.created_at.desc()).all()]


@router.get("/client/invoices/{invoice_id}", response_model=InvoiceResponse)
def get_client_invoice(
    invoice_id: str,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    invoice = _load_invoice(db).filter(
        Invoice.id == invoice_id, Invoice.client_id == client.id,
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _build_response(invoice)


@router.post("/client/invoices/{invoice_id}/confirm-payment", response_model=InvoiceResponse)
def confirm_payment(
    invoice_id: str,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Called when the client returns from Stripe checkout (?paid=true).
    Polls Stripe directly to verify payment status — does not rely on webhooks.
    """
    invoice = _load_invoice(db).filter(
        Invoice.id == invoice_id,
        Invoice.client_id == client.id,
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.status == InvoiceStatus.PAID:
        return _build_response(invoice)

    if not invoice.stripe_checkout_session_id:
        raise HTTPException(status_code=400, detail="No Stripe session associated with this invoice")

    therapist = invoice.therapist
    if not (therapist and therapist.stripe_account_id):
        raise HTTPException(status_code=400, detail="Therapist Stripe account not found")

    try:
        session = stripe.checkout.Session.retrieve(
            invoice.stripe_checkout_session_id,
            stripe_account=therapist.stripe_account_id,
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=f"Could not verify payment with Stripe: {e}")

    if session.payment_status != "paid":
        raise HTTPException(status_code=400, detail="Payment not completed in Stripe")

    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = datetime.utcnow()
    if session.payment_intent:
        invoice.stripe_payment_intent_id = str(session.payment_intent)
        existing = db.query(Payment).filter(
            Payment.stripe_payment_intent_id == str(session.payment_intent)
        ).first()
        if not existing:
            db.add(Payment(
                invoice_id=invoice.id,
                amount=invoice.amount,
                stripe_payment_intent_id=str(session.payment_intent),
                status="succeeded",
                paid_at=datetime.utcnow(),
            ))

    db.commit()
    issue_accounting_receipt(invoice, db, payment_method="online")
    return _build_response(_load_invoice(db).filter(Invoice.id == invoice_id).first())


@router.get("/client/invoices/{invoice_id}/pay")
def get_payment_link(
    invoice_id: str,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    invoice = _load_invoice(db).filter(
        Invoice.id == invoice_id, Invoice.client_id == client.id,
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == InvoiceStatus.PAID:
        raise HTTPException(status_code=400, detail="Invoice already paid")
    if not invoice.stripe_payment_link:
        therapist = invoice.therapist
        if not therapist.stripe_connected:
            raise HTTPException(status_code=400, detail="Therapist has not connected Stripe")
        session = create_checkout_session(
            invoice=invoice, therapist=therapist,
            success_url=f"{settings.FRONTEND_URL}/client/invoices?paid=true&invoice_id={invoice.id}",
            cancel_url=f"{settings.FRONTEND_URL}/client/invoices",
        )
        invoice.stripe_checkout_session_id = session["id"]
        invoice.stripe_payment_link = session["url"]
        db.commit()
    return {"payment_url": invoice.stripe_payment_link}


# ─── PDF download (both roles) ────────────────────────────────────────────────

@router.get("/therapist/invoices/{invoice_id}/pdf")
def download_invoice_pdf_therapist(
    invoice_id: str,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    invoice = _load_invoice(db).filter(
        Invoice.id == invoice_id, Invoice.therapist_id == therapist.id,
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _generate_pdf_response(invoice)


@router.get("/client/invoices/{invoice_id}/pdf")
def download_invoice_pdf_client(
    invoice_id: str,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    invoice = _load_invoice(db).filter(
        Invoice.id == invoice_id, Invoice.client_id == client.id,
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _generate_pdf_response(invoice)


def _generate_pdf_response(invoice: Invoice) -> Response:
    therapist = invoice.therapist
    client = invoice.client

    # Build line items list for PDF
    line_items = []
    for item in invoice.items:
        appt = item.appointment
        line_items.append({
            "description": item.description,
            "date": appt.start_time.strftime("%B %d, %Y") if appt else "N/A",
            "session_type": appt.session_type if appt else "Session",
            "amount": float(item.amount),
        })

    if not line_items and invoice.appointment:
        appt = invoice.appointment
        line_items = [{
            "description": "Therapy Session",
            "date": appt.start_time.strftime("%B %d, %Y") if appt else "N/A",
            "session_type": appt.session_type if appt else "Session",
            "amount": float(invoice.amount),
        }]

    pdf_bytes = generate_invoice_pdf(
        invoice_number=invoice.invoice_number,
        therapist_name=therapist.name,
        therapist_email=therapist.email,
        therapist_license=therapist.license_number,
        client_name=client.name,
        client_email=client.email,
        line_items=line_items,
        amount=float(invoice.amount),
        status=invoice.status,
        due_date=invoice.due_date.strftime("%B %d, %Y"),
        paid_at=invoice.paid_at.strftime("%B %d, %Y") if invoice.paid_at else None,
        invoice_id=str(invoice.id),
        payment_instructions=therapist.payment_instructions,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="invoice-{invoice.invoice_number}.pdf"'},
    )
