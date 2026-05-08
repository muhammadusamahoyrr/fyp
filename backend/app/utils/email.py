import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings


async def _send(to: str, subject: str, html: str) -> None:
    if not settings.smtp_user:
        # Email not configured — skip silently in development
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        start_tls=True,
    )


async def send_password_reset_email(email: str, token: str) -> None:
    reset_url = f"{settings.frontend_url}/reset-password?token={token}"
    html = f"""
    <h2>Password Reset — Attorney.AI</h2>
    <p>Click the link below to reset your password. This link expires in 1 hour.</p>
    <a href="{reset_url}">{reset_url}</a>
    <p>If you did not request this, ignore this email.</p>
    """
    await _send(email, "Reset your Attorney.AI password", html)


async def send_kyc_result_email(
    email: str, approved: bool, reason: str | None = None
) -> None:
    if approved:
        html = """
        <h2>KYC Approved — Attorney.AI</h2>
        <p>Your lawyer profile has been verified. You can now receive cases on the platform.</p>
        """
        subject = "Your Attorney.AI lawyer profile is verified"
    else:
        html = f"""
        <h2>KYC Rejected — Attorney.AI</h2>
        <p>Your verification could not be completed.</p>
        <p><strong>Reason:</strong> {reason or 'Not specified'}</p>
        <p>Please update your profile and resubmit.</p>
        """
        subject = "Attorney.AI verification update"

    await _send(email, subject, html)
