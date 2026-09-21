"""The executed agreement as a document, with an evidence certificate.

Until now a fully executed agreement existed only as a database row. The
signatures, the timestamps and the body digest were recorded faithfully and
readable by nobody, which for a legal product is the part that matters.

WHAT THIS DOCUMENT CLAIMS, AND WHAT IT DOES NOT
-----------------------------------------------
The certificate states FACTS THAT WERE RECORDED: who signed, what they typed
or drew, when the SERVER observed it, and the digest of the text they signed.

It does NOT say the agreement is enforceable, valid, binding, or of any
particular class under the Electronic Transactions Ordinance. Those are legal
conclusions. Nobody with the standing to reach them has reviewed this output,
and a document that asserts them would be making a claim its author cannot
support -- the same failure Phase 0 removed from the marketing copy. ETO
classification is deliberately absent and stays absent until counsel review
(Phase 4).

TIMESTAMPS ARE THE SERVER'S
---------------------------
Every time printed is the moment the server recorded the event, in UTC, and
says so. A client clock is whatever the signer's machine claimed; presenting
it as the time of signing would be repeating an unverified assertion in a
document meant to be evidence.

ESCAPING
--------
Everything that came from a user goes through `P()` from `pdf_generator`,
which escapes by default. reportlab's Paragraph parses a markup language: an
unescaped `<` in ordinary legal text ("the defendant paid <50% of what was
owed") raises a parser error, and an `<img src="...">` in a field opens that
path ON THE SERVER and embeds the file in the output. Text is data here, with
no exceptions and no `raw=True` on any interpolated value.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.pdf_generator import P, _styles

#: What the certificate says instead of an IP it cannot stand behind (D8).
IP_NOT_RECORDED = "not recorded"

#: Shown for a signature method the document has no wording for, rather than
#: printing the raw enum value as though it were a description.
UNKNOWN_METHOD = "recorded"

_METHOD_WORDING = {
    "typed": "typed their name",
    "drawn": "drew a signature",
    "uploaded": "uploaded a signature image",
}


def _utc(value) -> str:
    """A server timestamp, stated as such. Empty when there is none."""
    if not isinstance(value, datetime):
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _method_wording(method: str | None) -> str:
    return _METHOD_WORDING.get(method or "", UNKNOWN_METHOD)


#: Audit actions that represent somebody putting their signature to the
#: document. `sent` is one: sign-and-send is a single act, and the sender's
#: signature is recorded under it.
_SIGNING_ACTIONS = {"signed", "sent"}


def signing_ips(agreement: dict) -> dict[str, str]:
    """actor_id -> the IP recorded when they signed, for actors that have one.

    THE IP IS NOT ON THE PARTY. It lives in `audit_log`, keyed by `actor_id`,
    written by `submit_signature` and `sign_and_send_draft`. A first version of
    this module read `party["ip_address"]`, which does not exist -- so every
    certificate would have said "not recorded" even where an address had been
    captured, understating the record on every document.

    The LAST signing entry per actor wins: an actor appears once in practice,
    and if that ever stops being true the most recent act is the one the
    signature reflects.
    """
    found: dict[str, str] = {}
    for entry in agreement.get("audit_log") or []:
        if entry.get("action") not in _SIGNING_ACTIONS:
            continue
        actor = entry.get("actor_id")
        ip = entry.get("ip_address")
        if actor and ip:
            found[actor] = str(ip)
    return found


def build_executed_pdf(agreement: dict) -> bytes:
    """Render an EXECUTED agreement. Returns PDF bytes.

    The caller is responsible for authorisation and for refusing anything that
    is not executed; this function renders what it is given.
    """
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=2.0 * cm, bottomMargin=2.0 * cm,
        title="Executed agreement",
    )

    small = ParagraphStyle("ev_small", parent=styles["body"], fontSize=8.5,
                           leading=12, textColor=colors.HexColor("#444444"))
    centred = ParagraphStyle("ev_centre", parent=small, alignment=TA_CENTER)
    mono = ParagraphStyle("ev_mono", parent=styles["body"], fontSize=8,
                          leading=11, fontName="Courier")

    story = []

    # ── the agreement itself ────────────────────────────────────────────────
    story.append(P(agreement.get("title") or "Agreement", styles["title"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#999999")))
    story.append(Spacer(1, 0.45 * cm))

    body = agreement.get("body_html") or ""
    for block in body.split("\n"):
        if block.strip():
            story.append(P(block, styles["body"]))
        else:
            story.append(Spacer(1, 0.25 * cm))

    story.append(Spacer(1, 0.8 * cm))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#999999")))
    story.append(Spacer(1, 0.4 * cm))

    # ── the evidence certificate ────────────────────────────────────────────
    cert = [P("Signature record", styles["heading"]),
            Spacer(1, 0.15 * cm),
            P("The facts below are what this system recorded. Times are the "
              "moment the server observed each event, in UTC. This record "
              "makes no statement about the agreement's legal effect.",
              small),
            Spacer(1, 0.35 * cm)]

    rows = [[P("Party", small), P("Signature", small),
             P("Recorded by the server", small)]]
    for party in agreement.get("parties", []):
        if party.get("signed"):
            # The signature itself, as given. `P` escapes it; a drawn or
            # uploaded signature is a data URI far too long to print, so the
            # METHOD is stated and the blob is not reproduced.
            method = party.get("signature_method")
            if method == "typed":
                mark = P(party.get("signature_data") or "", small)
            else:
                mark = P(_method_wording(method), small)
            when = _utc(party.get("signed_at"))
        else:
            mark = P("did not sign", small)
            when = ""

        rows.append([
            P(party.get("full_name") or party.get("user_id") or "", small),
            mark,
            P(when, small),
        ])

    table = Table(rows, colWidths=[5.4 * cm, 5.4 * cm, 5.8 * cm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0F0F0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    cert.append(table)
    cert.append(Spacer(1, 0.4 * cm))

    # How each party signed, and from where if that is knowable.
    ips = signing_ips(agreement)
    for party in agreement.get("parties", []):
        if not party.get("signed"):
            continue
        name = party.get("full_name") or party.get("user_id") or ""
        ip = ips.get(party.get("user_id"))
        # D8: an address that could not be verified is OMITTED rather than
        # printed with a caveat. "not recorded" is true; a proxy's address
        # presented as the signer's is not.
        where = f" from {ip}" if ip else f" (origin {IP_NOT_RECORDED})"
        cert.append(P(
            f"{name} {_method_wording(party.get('signature_method'))}"
            f"{where} on {_utc(party.get('signed_at'))}.", small))

    cert.append(Spacer(1, 0.35 * cm))
    digest = agreement.get("body_sha256") or ""
    cert.append(P("Digest of the signed text (SHA-256)", small))
    cert.append(P(digest, mono))
    cert.append(Spacer(1, 0.2 * cm))
    cert.append(P(
        "This digest was computed from the agreement text at the moment it "
        "was sent for signature. Re-computing it over the text above will "
        "reproduce this value if the text has not changed.", small))

    cert.append(Spacer(1, 0.45 * cm))
    cert.append(P(
        f"Agreement reference {agreement.get('_id') or agreement.get('id') or ''} "
        f"· generated {_utc(datetime.now(timezone.utc))}", centred))

    story.append(KeepTogether(cert))

    doc.build(story)
    return buffer.getvalue()
