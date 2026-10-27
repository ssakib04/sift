import html
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.core.config import Settings


class InviteSender(Protocol):
    def send(
        self,
        to_address: str,
        subject: str,
        body: str,
        *,
        html: str = "",
        attachment_ics: str = "",
    ) -> None:
        """Deliver one invitation email, with a calendar file when one is ready."""


class SmtpInviteSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(
        self,
        to_address: str,
        subject: str,
        body: str,
        *,
        html: str = "",
        attachment_ics: str = "",
    ) -> None:
        message = EmailMessage()
        message["From"] = self._settings.invite_from_address
        message["To"] = to_address
        message["Subject"] = subject
        message.set_content(body)
        if html.strip():
            message.add_alternative(html, subtype="html")
        if attachment_ics.strip():
            message.add_attachment(
                attachment_ics.encode("utf-8"),
                maintype="text",
                subtype="calendar",
                filename="interview.ics",
            )
            for part in message.iter_attachments():
                if part.get_content_subtype() == "calendar":
                    part.set_param("method", "REQUEST")
        username, password = _smtp_credentials(self._settings)
        with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=20) as client:
            if username and password:
                client.ehlo()
                client.starttls()
                client.ehlo()
                client.login(username, password)
            client.send_message(message)


def _smtp_credentials(settings: Settings) -> tuple[str, str]:
    """Use SMTP login when set, otherwise the same mailbox that receives CVs."""
    username = settings.smtp_username.strip() or settings.imap_username.strip()
    password = settings.smtp_password.strip() or settings.imap_password.strip()
    return username, password


def invitation_body(
    *,
    candidate_name: str,
    job_title: str,
    company_name: str,
    url: str,
    when_label: str,
    calendar_line: str,
) -> str:
    who = candidate_name.strip()
    opening = f"Congratulations, {who}." if who else "Congratulations."
    company = company_name.strip() or "our company"
    return (
        f"Dear {who or 'there'},\n\n"
        f"{opening}\n\n"
        f"Thank you for applying for {job_title} at {company}. "
        "We have reviewed your application and would like to invite you to a video interview.\n\n"
        f"Your interview is scheduled for {when_label}.\n"
        f"{calendar_line}\n\n"
        "Please join from a quiet place, with your camera and microphone ready. "
        "There is nothing extra to install. When it is time, open your interview here:\n"
        f"{url}\n\n"
        "The conversation is about your experience and how you would approach the work. "
        "If this time no longer suits you, reply to this email and we will look for another slot.\n\n"
        "We look forward to speaking with you.\n\n"
        "Warm regards,\n"
        "The Hiring Team\n"
        f"{company}\n"
    )


def invitation_html(
    *,
    candidate_name: str,
    job_title: str,
    company_name: str,
    url: str,
    when_label: str,
    calendar_line: str,
) -> str:
    who = candidate_name.strip()
    company = company_name.strip() or "our company"
    opening = f"Congratulations, {who}." if who else "Congratulations."
    return letter_html(
        company_name=company,
        headline="Your video interview",
        greeting=f"Dear {who or 'there'},",
        paragraphs=[
            opening,
            f"Thank you for applying for {job_title} at {company}. We have reviewed your application and would like to invite you to a video interview.",
        ],
        details=[("Role", job_title), ("When", when_label)],
        note=calendar_line,
        action_label="Join your video interview",
        action_url=url,
        closing=[
            "Please join from a quiet place, with your camera and microphone ready. There is nothing extra to install.",
            "The conversation is about your experience and how you would approach the work. If this time no longer suits you, reply to this email and we will look for another slot.",
        ],
        signoff=f"We look forward to speaking with you.\nWarm regards,\nThe Hiring Team\n{company}",
    )


def letter_html(
    *,
    company_name: str,
    headline: str,
    greeting: str,
    paragraphs: list[str],
    signoff: str,
    details: list[tuple[str, str]] | None = None,
    note: str = "",
    action_label: str = "",
    action_url: str = "",
    closing: list[str] | None = None,
) -> str:
    """A single-column letter that mail clients can render without a stylesheet."""
    company = _esc(company_name.strip() or "Sift")
    return (
        "<!DOCTYPE html>"
        '<html lang="en"><body style="margin:0;padding:0;background:#f3ece6;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3ece6;padding:32px 12px;">'
        '<tr><td align="center">'
        '<table role="presentation" width="560" cellpadding="0" cellspacing="0" '
        'style="width:100%;max-width:560px;background:#fffdfb;border:1px solid #e6d9d2;">'
        '<tr><td style="background:#6e2e3c;padding:22px 32px;">'
        f'<p style="margin:0;font-family:Georgia,Times New Roman,serif;font-size:12px;letter-spacing:0.18em;'
        f'text-transform:uppercase;color:#f3d5dc;">{company}</p>'
        f'<p style="margin:8px 0 0;font-family:Georgia,Times New Roman,serif;font-size:24px;line-height:1.3;color:#fffaf7;">'
        f"{_esc(headline)}</p>"
        "</td></tr>"
        '<tr><td style="padding:28px 32px 8px;">'
        f'<p style="margin:0 0 16px;font-family:Georgia,Times New Roman,serif;font-size:16px;line-height:1.65;color:#2c2426;">'
        f"{_esc(greeting)}</p>"
        f"{_paragraphs(paragraphs)}"
        f"{_details(details or [])}"
        f"{_paragraphs([note])}"
        f"{_action(action_label, action_url)}"
        f"{_paragraphs(closing or [])}"
        f"{_signoff(signoff)}"
        "</td></tr>"
        '<tr><td style="padding:4px 32px 28px;">'
        '<p style="margin:0;font-family:Georgia,Times New Roman,serif;font-size:12px;line-height:1.5;color:#8a7c7f;">'
        f"Sent by the hiring team at {company}."
        "</p></td></tr></table></td></tr></table></body></html>"
    )


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


def _paragraphs(paragraphs: list[str]) -> str:
    return "".join(
        '<p style="margin:0 0 16px;font-family:Georgia,Times New Roman,serif;font-size:16px;line-height:1.65;color:#2c2426;">'
        f"{_esc(paragraph)}</p>"
        for paragraph in paragraphs
        if paragraph.strip()
    )


def _details(rows: list[tuple[str, str]]) -> str:
    filled = [(label, value) for label, value in rows if label.strip() and value.strip()]
    if not filled:
        return ""
    cells = "".join(
        "<tr>"
        '<td style="padding:10px 18px 10px 0;font-family:Georgia,Times New Roman,serif;font-size:13px;'
        f'color:#6d5e61;vertical-align:top;">{_esc(label)}</td>'
        '<td style="padding:10px 0;font-family:Georgia,Times New Roman,serif;font-size:15px;line-height:1.45;color:#2c2426;">'
        f"{_esc(value)}</td></tr>"
        for label, value in filled
    )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'style="width:100%;margin:0 0 18px;border-top:1px solid #eadfd8;border-bottom:1px solid #eadfd8;">'
        f"{cells}</table>"
    )


def _action(label: str, url: str) -> str:
    if not label.strip() or not url.strip():
        return ""
    safe_url = _esc(url.strip())
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:4px 0 18px;"><tr>'
        '<td style="border-radius:4px;background:#7a3544;">'
        f'<a href="{safe_url}" style="display:inline-block;padding:12px 22px;font-family:Georgia,Times New Roman,serif;'
        f'font-size:15px;line-height:1.2;color:#fffaf7;text-decoration:none;">{_esc(label.strip())}</a>'
        "</td></tr></table>"
        '<p style="margin:0 0 16px;font-family:Georgia,Times New Roman,serif;font-size:13px;line-height:1.5;color:#6d5e61;">'
        f'Or copy this link into your browser:<br><a href="{safe_url}" style="color:#7a3544;">{safe_url}</a></p>'
    )


def _signoff(signoff: str) -> str:
    lines = "<br>".join(_esc(line) for line in signoff.split("\n") if line.strip())
    return (
        '<p style="margin:8px 0 0;font-family:Georgia,Times New Roman,serif;font-size:16px;line-height:1.6;color:#2c2426;">'
        f"{lines}</p>"
    )
