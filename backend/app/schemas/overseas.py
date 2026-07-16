from datetime import datetime

from pydantic import BaseModel


class POAOut(BaseModel):
    """A Power-of-Attorney record (create / list / get / revoke / execution /
    acknowledge).

    STRICT allowlist — no ``extra="allow"``. This is CNIC-sensitive data, so
    defense-in-depth: the service's ``_public`` already drops every ``*_encrypted``
    key, but declaring an explicit allowlist here GUARANTEES the encrypted CNIC
    blobs (``principal_cnic_encrypted`` / ``attorney_cnic_encrypted``) can never
    reach the client even if a future refactor returns a raw doc bypassing
    ``_public``. Only the masked CNICs are surfaced. ``expiry_notified`` (an
    internal scheduler flag) is intentionally omitted too.

    The service renames ``_id`` → ``id`` (the UI reads ``p.id``). ``expiring_soon``
    is added only on the ``_decorate`` paths (absent on create), hence optional.
    ``principal_snapshot`` stays ``dict | None`` (immutable denormalized copy).
    """
    id: str
    principal_id: str | None = None
    principal_snapshot: dict | None = None
    attorney_name: str | None = None
    principal_cnic_masked: str | None = None
    attorney_cnic_masked: str | None = None
    attorney_relation: str | None = None
    poa_type: str | None = None
    subject: str | None = None
    powers: list[str] | None = None
    restrictions: str | None = None
    country_of_execution: str | None = None
    issue_date: str | None = None
    expiry_date: datetime | None = None
    status: str | None = None
    execution_status: str | None = None
    attorney_ack_status: str | None = None
    attorney_ack_at: datetime | None = None
    document_id: str | None = None
    document_sha256: str | None = None
    revocation_document_id: str | None = None
    revocation_sha256: str | None = None
    revoked_at: datetime | None = None
    expiring_soon: bool | None = None
    # Point-of-use verification (added with the Verifiable-POA work). verify_url is
    # the owner-facing link/QR target; the raw verify_token is deliberately NOT
    # surfaced here (the URL already carries it). opppa_status tracks OPPPA
    # registration. Both are non-sensitive.
    verify_url: str | None = None
    opppa_status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
