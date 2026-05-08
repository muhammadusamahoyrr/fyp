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


class SignatureMethod(str, Enum):
    CANVAS = "canvas"
    TYPED = "typed"
    IMAGE_UPLOAD = "image_upload"


class AgreementStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    EXECUTED = "executed"
    CANCELLED = "cancelled"


class NotificationType(str, Enum):
    CASE_UPDATE = "case_update"
    LAWYER_ASSIGNED = "lawyer_assigned"
    HEARING_SCHEDULED = "hearing_scheduled"
    DOCUMENT_READY = "document_ready"
    AGREEMENT_SIGNED = "agreement_signed"
    KYC_APPROVED = "kyc_approved"
    KYC_REJECTED = "kyc_rejected"
    REVIEW_RECEIVED = "review_received"
