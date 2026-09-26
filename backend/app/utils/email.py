import logging
from datetime import datetime

import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


async def _send(to: str, subject: str, html: str) -> bool:
    """Send an email. Returns False (and logs a warning) when SMTP is not
    configured; raises on a real delivery failure so callers can decide
    whether the operation must fail loudly."""
    if not settings.smtp_user:
        logger.warning("SMTP not configured; email was not sent")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=True,
        )
    except Exception as exc:
        # Recipient addresses are personal data and SMTP errors can expose host
        # details. Callers need the exception; logs need only a safe category.
        logger.error("Email delivery failed; error_type=%s", type(exc).__name__)
        raise
    return True


async def send_password_reset_email(email: str, token: str) -> bool:
    reset_url = f"{settings.frontend_url}/reset-password?token={token}"
    html = f"""
    <h2>Password Reset — Attorney.AI</h2>
    <p>Click the link below to reset your password. This link expires in 1 hour.</p>
    <a href="{reset_url}">{reset_url}</a>
    <p>If you did not request this, ignore this email.</p>
    """
    return await _send(email, "Reset your Attorney.AI password", html)


def classify_delivery_error(exc: Exception) -> str:
    """A stable, non-identifying reason code for a failed send.

    The caller stores this and the UI renders it, so it must never carry the
    SMTP text: that names the recipient and the relay host. What it must carry
    is the DIFFERENCE between failures, because they need different actions.
    "delivery_failed" for everything told the sender nothing -- a provider's
    daily cap, a temporary deferral and a permanent rejection all looked the
    same, and the first two resolve by waiting while the third never does.
    """
    code = getattr(exc, "code", None)
    text = str(getattr(exc, "message", "") or exc)

    # 550 5.4.5 from Gmail: the account has sent as much as it may today.
    # Nothing is wrong with the message or the address.
    if "5.4.5" in text or "sending limit" in text.lower():
        return "provider_daily_limit"
    # 4xx is SMTP for "try later".
    if isinstance(code, int) and 400 <= code < 500:
        return "provider_temporarily_unavailable"
    if isinstance(code, int) and 500 <= code < 600:
        return "rejected_by_provider"
    return "delivery_failed"


async def send_agreement_notification_email(
    email: str,
    *,
    title: str,
    sender_name: str,
    recipient_name: str | None = None,
) -> bool:
    """Tell a REGISTERED party that an agreement is waiting for them.

    NO TOKEN, AND THAT IS THE POINT. This person has an account, so the way in
    is their own login. Emailing a bearer link to somebody who can already
    authenticate would create a second, weaker path to the same signature --
    one that works for anyone who reads their inbox, and that the audit trail
    would record as an unverified signer.

    It exists because an in-app notification only arrives if the recipient
    happens to log in. Nothing prompts them to. A counterparty can sit unaware
    of an agreement for days, which reads as the product having done nothing.

    Returns False when SMTP is unconfigured; raises on a real delivery failure.
    The caller treats both as non-fatal: the in-app notification is the record
    of record, and this is the nudge towards it.
    """
    link = f"{settings.frontend_url}/agreements"
    greeting = f"Hello {_esc(recipient_name)}," if recipient_name else "Hello,"
    html = f"""
    <h2>An agreement is waiting for your signature</h2>
    <p>{greeting}</p>
    <p><strong>{_esc(sender_name)}</strong> has sent you
       &ldquo;{_esc(title)}&rdquo; to sign on Attorney.AI.</p>
    <p><a href="{link}">Open your Agreements page</a></p>
    <p>Sign in with your usual account to read it and sign. This message
       contains no signing link, so forwarding it gives nobody access.</p>
    """
    return await _send(
        email, f"{sender_name} sent you “{title}” to sign", html)


def _esc(value: str | None) -> str:
    """Escape a value before it goes into the HTML body.

    Every field below is attacker-influenced: a signer's name and an agreement
    title are typed by a user, and this template is HTML. Without escaping, a
    title containing a tag would be rendered as markup in someone else's inbox.
    """
    from html import escape
    return escape(value or "", quote=True)


async def send_agreement_invitation_email(
    email: str,
    *,
    token: str,
    title: str,
    sender_name: str,
    signer_name: str | None = None,
    expires_at: "datetime | None" = None,
) -> bool:
    """Invite someone with no account to sign one agreement.

    THE AGREEMENT TEXT IS NOT IN HERE, deliberately. This carries the title, who
    is asking, and a one-time link. The instrument itself stays behind that
    link, where the token is single-use and the read is recorded -- an emailed
    copy would be a second version of a legal document, in a channel that
    forwards and archives it, with no relationship to the one actually signed.

    THE LINK IS BEARER AUTHORITY. Anyone holding it can sign that slot, which is
    why the message says so plainly rather than implying the recipient is
    identified. `invitation_token.DEFAULT_TTL_DAYS` bounds the exposure.

    Returns False when SMTP is unconfigured (the caller falls back to handing
    the link to the sender); raises on a real delivery failure.
    """
    link = f"{settings.frontend_url}/sign?token={token}"
    greeting = f"Hello {_esc(signer_name)}," if signer_name else "Hello,"
    expiry_line = (
        f"<p>This link stops working on "
        f"{expires_at.strftime('%d %b %Y')}.</p>" if expires_at else ""
    )
    html = f"""
    <h2>An agreement is waiting for your signature</h2>
    <p>{greeting}</p>
    <p><strong>{_esc(sender_name)}</strong> has asked you to sign
       &ldquo;{_esc(title)}&rdquo; on Attorney.AI.</p>
    <p><a href="{link}">Review and sign the agreement</a></p>
    <p>You do not need an account. Opening the link shows you the agreement and
       lets you sign your part of it.</p>
    {expiry_line}
    <p>Anyone with this link can sign in your name, so do not forward it. We do
       not verify the identity of whoever signs.</p>
    <p>If you were not expecting this, you can ignore this email and nothing
       will be signed.</p>
    """
    return await _send(
        email, f"{sender_name} asked you to sign “{title}”", html)


async def send_kyc_result_email(
    email: str, approved: bool, reason: str | None = None
) -> bool:
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

    return await _send(email, subject, html)
