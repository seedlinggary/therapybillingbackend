from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
import resend
from app.config import settings

router = APIRouter(tags=["contact"])

resend.api_key = settings.RESEND_API_KEY

CONTACT_EMAIL = "gary.s.schwartz617@gmail.com"


class ContactForm(BaseModel):
    name: str
    email: EmailStr
    subject: str
    message: str


@router.post("/contact", status_code=204)
def submit_contact(data: ContactForm):
    try:
        html = f"""
        <h2>New contact form submission — PracticeBilling</h2>
        <table style="border-collapse:collapse;width:100%;max-width:600px">
          <tr><td style="padding:8px 0;font-weight:bold;color:#374151;width:120px">From</td>
              <td style="padding:8px 0;color:#111827">{data.name} &lt;{data.email}&gt;</td></tr>
          <tr><td style="padding:8px 0;font-weight:bold;color:#374151">Subject</td>
              <td style="padding:8px 0;color:#111827">{data.subject}</td></tr>
        </table>
        <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0"/>
        <h3 style="color:#374151;margin-bottom:8px">Message</h3>
        <p style="color:#111827;line-height:1.6;white-space:pre-wrap">{data.message}</p>
        <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0"/>
        <p style="color:#6b7280;font-size:12px">
          Reply directly to this email to respond to {data.name}.
        </p>
        """
        resend.Emails.send({
            "from": f"PracticeBilling Contact <{settings.EMAIL_FROM}>",
            "to": CONTACT_EMAIL,
            "reply_to": data.email,
            "subject": f"[PracticeBilling] {data.subject} — from {data.name}",
            "html": html,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to send message")
