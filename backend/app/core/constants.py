from enum import Enum


class UserRole(str, Enum):
    CLIENT = "client"
    LAWYER = "lawyer"
    ADMIN = "admin"


class KycStatus(str, Enum):
    """Where a lawyer's verification actually stands.

    `kyc_verified: bool` alone could not express this. A REJECTED lawyer has
    kyc_verified False and so matched the pending-queue filter exactly as an
    unreviewed one did — rejections silently looped back into the queue forever
    and were re-reviewed with no record that a decision had already been made.

    REJECTED is terminal until the lawyer takes an explicit resubmit action,
    which is the only transition back to PENDING. `kyc_verified` stays as the
    authoritative gate on receiving cases; this says how it got there.
    """
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CaseType(str, Enum):
    CIVIL = "civil"
    CRIMINAL = "criminal"
    CONSTITUTIONAL = "constitutional"
    FAMILY = "family"


class Province(str, Enum):
    PUNJAB = "punjab"
    SINDH = "sindh"
    KPK = "kpk"
    BALOCHISTAN = "balochistan"
    FEDERAL = "federal"


class CaseStatus(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING_LAWYER = "pending_lawyer"
    CLOSED = "closed"
    DISMISSED = "dismissed"


# The matter is over. Retention reads this: `closed_at` is stamped on entering
# one of these and cleared on leaving, and the case-data period runs from it.
#
# Defined once because two copies would drift, and a drifted copy here means a
# case that is over by one module's reckoning and live by another's — the clock
# either never starts or never stops, and neither failure is visible until the
# data is gone or kept for ever.
TERMINAL_CASE_STATUSES = frozenset({
    CaseStatus.CLOSED.value,
    CaseStatus.DISMISSED.value,
})


class IntakeStep(int, Enum):
    ONE = 1
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5


class DocumentTemplate(str, Enum):
    PLAINT_CIVIL = "plaint_civil"
    WRITTEN_STATEMENT = "written_statement"
    LEGAL_NOTICE = "legal_notice"
    NDA = "nda"
    RENTAL_AGREEMENT = "rental_agreement"
    INHERITANCE_SETTLEMENT = "inheritance_settlement"
    INHERITANCE_DEMAND = "inheritance_demand"
    FIR_APPLICATION = "fir_application"
    COMPLAINT_154_3 = "complaint_154_3"
    PETITION_22A = "petition_22a"
    FIA_CYBERCRIME = "fia_cybercrime"
    WASIYYAT_NAMA = "wasiyyat_nama"
    POWER_OF_ATTORNEY = "power_of_attorney"
    POA_REVOCATION = "poa_revocation"
    LABOUR_DEMAND = "labour_demand"
    BAIL_APPLICATION = "bail_application"
    URDU_PLEADING = "urdu_pleading"
    DISPUTE_PETITION = "dispute_petition"
    GUARDIANSHIP_PETITION = "guardianship_petition"
    WAKALATNAMA_CHECKLIST = "wakalatnama_checklist"
    # Free prose written by a lawyer on the drafting page. Unlike every other
    # member, this names no particular instrument — see the builder.
    LAWYER_DRAFT = "lawyer_draft"


class DocumentReviewStatus(str, Enum):
    DRAFT = "draft"          # generated, not yet sent to a lawyer
    SUBMITTED = "submitted"  # waiting for lawyer review
    APPROVED = "approved"    # lawyer signed off
    RETURNED = "returned"    # lawyer wants changes — client can edit & resubmit
    REJECTED = "rejected"    # lawyer rejected outright


class SignatureMethod(str, Enum):
    CANVAS = "canvas"
    TYPED = "typed"
    IMAGE_UPLOAD = "image_upload"


class AgreementStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    EXECUTED = "executed"
    CANCELLED = "cancelled"


class EngagementStatus(str, Enum):
    """The lifecycle of one client-lawyer engagement.

        requested ──lawyer proposes terms──► terms_proposed
                                                  │
                          client accepts ◄────────┴────────► client declines
                                  │                                │
                                  ▼                                ▼
                              accepted                         declined
                             │        │
                    complete │        │ terminate
                             ▼        ▼
                        completed   terminated

    `terms_proposed` is the state this enum existed without, and its absence was
    the whole defect: the lawyer set a fee and claimed the case in a single
    call, so the client first learned the price from a relationship they were
    already in and could not leave. Nothing is claimed until `accepted`, and
    `accepted` is now a state with exits rather than an absorbing one.
    """

    REQUESTED = "requested"
    TERMS_PROPOSED = "terms_proposed"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    TERMINATED = "terminated"


# An engagement that is still being negotiated: a lawyer has been asked, and
# neither side has walked away. One per case — see `uniq_pending_engagement`.
ENGAGEMENT_OPEN_STATUSES = (
    EngagementStatus.REQUESTED.value,
    EngagementStatus.TERMS_PROPOSED.value,
)

# An engagement that became a real working relationship. An engagement that has
# since ended still happened, and still counts.
#
# NECESSARY BUT NO LONGER SUFFICIENT for either gate. Both billing
# (`payment_service._require_executed_engagement_letter`) and reviews
# (`engagement_repo.exists_executed_relationship`) now ALSO require the
# engagement's letter to be `executed`. Membership here alone once implied both,
# and that was the hole: a declined letter left the engagement `accepted`, so a
# client could review — and a lawyer be told to chase — a relationship neither
# party had signed.
ENGAGEMENT_RETAINED_STATUSES = (
    EngagementStatus.ACCEPTED.value,
    EngagementStatus.COMPLETED.value,
    EngagementStatus.TERMINATED.value,
)


class EngagementFeeType(str, Enum):
    FIXED = "fixed"
    HOURLY = "hourly"
    PER_HEARING = "per_hearing"


class PaymentStatus(str, Enum):
    CREATED = "created"      # fee request raised, no checkout yet
    PENDING = "pending"      # checkout started, awaiting settlement
    PAID = "paid"            # settled
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"      # unpaid past expires_at
    REFUNDED = "refunded"


class PaymentKind(str, Enum):
    FEE = "fee"                    # client → lawyer
    SUBSCRIPTION = "subscription"  # lawyer → platform


class PaymentPurpose(str, Enum):
    PESHI_FEE = "peshi_fee"              # per court appearance
    PROFESSIONAL_FEE = "professional_fee"
    SUBSCRIPTION = "subscription"


class PaymentProvider(str, Enum):
    MOCK = "mock"
    SAFEPAY = "safepay"


class SubscriptionTier(str, Enum):
    FREE = "free"
    PROFESSIONAL = "professional"
    FIRM = "firm"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    TRIALING = "trialing"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class BillingCycle(str, Enum):
    MONTHLY = "monthly"
    ANNUAL = "annual"


class POAStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class POAExecutionStatus(str, Enum):
    DRAFTED = "drafted"
    NOTARIZED = "notarized"
    MISSION_ATTESTED = "mission_attested"
    MOFA_ATTESTED = "mofa_attested"
    REGISTERED = "registered"


class POAAckStatus(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"


# Powers that dispose of property — barred from a General POA (must be a Special POA).
PROPERTY_DISPOSITION_POWERS = {"sell", "transfer", "gift", "mortgage"}


class NotificationType(str, Enum):
    CASE_UPDATE = "case_update"
    # Case messaging is the working channel between client and lawyer, and it
    # had no notification type at all — a message was stored and surfaced only
    # if the other party happened to reopen the case. Clients on Desktop-plus-
    # WhatsApp habits do not poll a web app.
    CASE_MESSAGE = "case_message"
    LAWYER_ASSIGNED = "lawyer_assigned"
    ENGAGEMENT_REQUESTED = "engagement_requested"
    # The client-facing half of the two-step flow. Terms arriving is the moment
    # a client first sees a price, so it is the one notification in this group
    # they must not miss.
    ENGAGEMENT_TERMS_PROPOSED = "engagement_terms_proposed"
    ENGAGEMENT_ACCEPTED = "engagement_accepted"
    ENGAGEMENT_DECLINED = "engagement_declined"
    ENGAGEMENT_CANCELLED = "engagement_cancelled"
    ENGAGEMENT_COMPLETION_PROPOSED = "engagement_completion_proposed"
    ENGAGEMENT_COMPLETED = "engagement_completed"
    ENGAGEMENT_TERMINATED = "engagement_terminated"
    HEARING_SCHEDULED = "hearing_scheduled"
    DOCUMENT_READY = "document_ready"
    DOCUMENT_SUBMITTED = "document_submitted"
    DOCUMENT_APPROVED = "document_approved"
    DOCUMENT_RETURNED = "document_returned"
    DOCUMENT_REJECTED = "document_rejected"
    DOCUMENT_WITHDRAWN = "document_withdrawn"   # client pulled a submission back (DOCUMENTS_V2)
    AGREEMENT_CREATED = "agreement_created"
    AGREEMENT_SIGNED = "agreement_signed"
    AGREEMENT_EXECUTED = "agreement_executed"
    AGREEMENT_DECLINED = "agreement_declined"
    KYC_APPROVED = "kyc_approved"
    KYC_REJECTED = "kyc_rejected"
    REVIEW_RECEIVED = "review_received"
    APPOINTMENT_BOOKED = "appointment_booked"
    APPOINTMENT_CONFIRMED = "appointment_confirmed"
    APPOINTMENT_CANCELLED = "appointment_cancelled"
    APPOINTMENT_COMPLETED = "appointment_completed"
    # Its own type, not a reuse of CANCELLED. A no-show and a cancellation are
    # different facts with different consequences: a cancellation is an
    # appointment called off, a no-show is one the client did not attend, and
    # only the second bears on them. The lawyer's page already learned this
    # distinction the hard way — it rendered `no_show` as "Cancelled" and told
    # a lawyer their client had called off when in fact the client had not
    # turned up.
    APPOINTMENT_NO_SHOW = "appointment_no_show"
    APPOINTMENT_EXPIRED = "appointment_expired"
    # RESERVED, and still unused: the T-24h / T-1h reminders before a
    # consultation. Kept distinct from the nudge below because the two say
    # opposite things — one is "this is about to happen", the other is "this
    # already happened and nobody recorded what came of it". A client filtering
    # or muting reminders must not thereby mute a lawyer's outstanding work,
    # and a single type would make the two indistinguishable for ever once
    # rows carrying it exist.
    APPOINTMENT_REMINDER = "appointment_reminder"
    APPOINTMENT_OUTCOME_NUDGE = "appointment_outcome_nudge"
    # The client hears the outcome of the report they filed. Its own type: a
    # client filtering appointment reminders must not thereby silence the
    # answer to a complaint they raised.
    APPOINTMENT_DISPUTE_RESOLVED = "appointment_dispute_resolved"
    # And the lawyer hears only when an appointment's RECORD was administratively
    # corrected — never that a report exists, which would tell them a client
    # complained about them whatever the outcome.
    APPOINTMENT_RECORD_CORRECTED = "appointment_record_corrected"
    CAUSELIST_LISTED = "causelist_listed"
    PAYMENT_REQUESTED = "payment_requested"
    PAYMENT_RECEIVED = "payment_received"
    PAYMENT_FAILED = "payment_failed"
    SUBSCRIPTION_ACTIVATED = "subscription_activated"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"
    POA_EXPIRING = "poa_expiring"
    DISPUTE_TRIAGE = "dispute_triage"   # a property dispute was held for lawyer triage
    DISPUTE_ASSIGNED = "dispute_assigned"  # a property-dispute case brief was sent to a lawyer


class AppointmentStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"
    # An unanswered request that stopped holding its slot. Terminal, and its
    # own thing: nobody cancelled it, so reusing CANCELLED would force
    # `cancelled_by` to name an actor who does not exist and would make "did my
    # lawyer decline?" unanswerable from the record.
    EXPIRED = "expired"


class AppointmentMode(str, Enum):
    VIDEO = "video"
    IN_PERSON = "in_person"
    PHONE = "phone"
