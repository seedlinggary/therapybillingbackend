import resend
from app.config import settings
from typing import Optional

resend.api_key = settings.RESEND_API_KEY


def _send(to: str, subject: str, html: str):
    resend.Emails.send({
        "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>",
        "to": to,
        "subject": subject,
        "html": html,
    })


def send_client_invite(client_email: str, client_name: str, therapist_name: str, invite_token: str):
    activate_url = f"{settings.FRONTEND_URL}/activate?token={invite_token}"
    html = f"""
    <h2>You've been invited to TherapyBilling</h2>
    <p>Hi {client_name},</p>
    <p><strong>{therapist_name}</strong> has added you as a client.</p>
    <p>Click below to set up your account and view your appointments and invoices:</p>
    <p><a href="{activate_url}" style="background:#4F46E5;color:white;padding:12px 24px;border-radius:6px;text-decoration:none;display:inline-block;">
        Activate Your Account
    </a></p>
    <p>This link expires in 72 hours.</p>
    """
    _send(client_email, f"You've been invited by {therapist_name}", html)


def send_appointment_confirmation(
    client_email: str,
    client_name: str,
    therapist_name: str,
    start_time: str,
    end_time: str,
    session_type: str,
):
    html = f"""
    <h2>Appointment Confirmed</h2>
    <p>Hi {client_name},</p>
    <p>Your {session_type} session with <strong>{therapist_name}</strong> has been scheduled.</p>
    <ul>
        <li><strong>Date/Time:</strong> {start_time}</li>
        <li><strong>Duration:</strong> Until {end_time}</li>
    </ul>
    <p>You can view your upcoming sessions at <a href="{settings.FRONTEND_URL}/client/sessions">your dashboard</a>.</p>
    """
    _send(client_email, f"Appointment confirmed with {therapist_name}", html)


def send_appointment_cancellation(
    client_email: str,
    client_name: str,
    therapist_name: str,
    start_time: str,
    reason: Optional[str] = None,
):
    reason_text = f"<p><strong>Reason:</strong> {reason}</p>" if reason else ""
    html = f"""
    <h2>Appointment Canceled</h2>
    <p>Hi {client_name},</p>
    <p>Your session with <strong>{therapist_name}</strong> on <strong>{start_time}</strong> has been canceled.</p>
    {reason_text}
    <p>Please contact your therapist to reschedule.</p>
    """
    _send(client_email, f"Appointment canceled - {start_time}", html)


def send_password_reset_email(client_email: str, client_name: str, code: str):
    html = f"""
    <h2>Password Reset</h2>
    <p>Hi {client_name},</p>
    <p>Your password reset code is:</p>
    <p style="font-size:36px;font-weight:bold;letter-spacing:10px;color:#4F46E5;margin:24px 0">{code}</p>
    <p>This code expires in 30 minutes.</p>
    <p style="color:#6b7280;font-size:14px">If you didn't request a password reset, you can safely ignore this email.</p>
    """
    _send(client_email, "Your password reset code", html)


def send_invoice_email(
    client_email: str,
    client_name: str,
    therapist_name: str,
    invoice_number: str,
    amount: float,
    due_date: str,
    payment_link: Optional[str],
    session_date: str,
    payment_instructions: Optional[str] = None,
    currency: str = "USD",
):
    symbol = "₪" if currency == "ILS" else "$"
    pay_button = ""
    if payment_link:
        pay_button = f"""
        <p><a href="{payment_link}" style="background:#4F46E5;color:white;padding:12px 24px;border-radius:6px;text-decoration:none;display:inline-block;">
            Pay Now {symbol}{amount:.2f}
        </a></p>
        """

    payment_instructions_html = ""
    if payment_instructions:
        payment_instructions_html = f"""
        <div style="margin-top:20px;padding:16px;background:#f9fafb;border-radius:8px;border:1px solid #e5e7eb">
            <p style="margin:0 0 8px;font-weight:600;color:#374151">Payment Instructions</p>
            <p style="margin:0;color:#4b5563;white-space:pre-line">{payment_instructions}</p>
        </div>
        """

    html = f"""
    <h2>Invoice #{invoice_number}</h2>
    <p>Hi {client_name},</p>
    <p>An invoice has been created for your session with <strong>{therapist_name}</strong>.</p>
    <table style="border-collapse:collapse;width:100%;max-width:400px">
        <tr><td style="padding:8px;border:1px solid #e5e7eb"><strong>Session Date</strong></td><td style="padding:8px;border:1px solid #e5e7eb">{session_date}</td></tr>
        <tr><td style="padding:8px;border:1px solid #e5e7eb"><strong>Amount</strong></td><td style="padding:8px;border:1px solid #e5e7eb">{symbol}{amount:.2f}</td></tr>
        <tr><td style="padding:8px;border:1px solid #e5e7eb"><strong>Due Date</strong></td><td style="padding:8px;border:1px solid #e5e7eb">{due_date}</td></tr>
    </table>
    {pay_button}
    {payment_instructions_html}
    <p style="margin-top:16px">You can also view and download your invoices at <a href="{settings.FRONTEND_URL}/client/invoices">your dashboard</a>.</p>
    """
    _send(client_email, f"Invoice #{invoice_number} from {therapist_name} - {symbol}{amount:.2f}", html)
