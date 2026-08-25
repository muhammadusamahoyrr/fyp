from enum import Enum


class UserRole(str, Enum):
    CLIENT = "client"
    LAWYER = "lawyer"
    ADMIN = "admin"


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
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"


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
    ENGAGEMENT_ACCEPTED = "engagement_accepted"
    ENGAGEMENT_DECLINED = "engagement_declined"
    ENGAGEMENT_CANCELLED = "engagement_cancelled"
    HEARING_SCHEDULED = "hearing_scheduled"
    DOCUMENT_READY = "document_ready"
    DOCUMENT_SUBMITTED = "document_submitted"
    DOCUMENT_APPROVED = "document_approved"
    DOCUMENT_RETURNED = "document_returned"
    DOCUMENT_REJECTED = "document_rejected"
    AGREEMENT_CREATED = "agreement_created"
    AGREEMENT_SIGNED = "agreement_signed"
    AGREEMENT_EXECUTED = "agreement_executed"
    KYC_APPROVED = "kyc_approved"
    KYC_REJECTED = "kyc_rejected"
    REVIEW_RECEIVED = "review_received"
    APPOINTMENT_BOOKED = "appointment_booked"
    APPOINTMENT_CONFIRMED = "appointment_confirmed"
    APPOINTMENT_CANCELLED = "appointment_cancelled"
    APPOINTMENT_COMPLETED = "appointment_completed"
    APPOINTMENT_REMINDER = "appointment_reminder"
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


class AppointmentMode(str, Enum):
    VIDEO = "video"
    IN_PERSON = "in_person"
    PHONE = "phone"
