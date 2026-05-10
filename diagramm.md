# Attorney.AI — Exact State Transition Diagrams
> Sourced directly from backend service implementations

---

## STD-1: Case Lifecycle — Exact Code Implementation

**Source:** `backend/app/services/case_service.py` + `backend/app/core/constants.py`

**State Definition:**
```python
class CaseStatus(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING_LAWYER = "pending_lawyer"
    CLOSED = "closed"
    DISMISSED = "dismissed"
```

**State Creation (from `case_service.py:15-35`):**
```python
async def create_case(client_id: str, data: dict) -> dict:
    doc = {
        "_id": case_id,
        "status": CaseStatus.OPEN.value,  # ← Always OPEN on creation
        "lawyer_id": None,                # ← NULL decides PENDING_LAWYER vs IN_PROGRESS
        ...
    }
```

**State Update (from `case_service.py:54-64`):**
```python
async def update_case(case_id: str, updates: dict, ...):
    updates["updated_at"] = datetime.utcnow()
    await case_repo.update_one({"_id": case_id}, {"$set": updates})
    # ← No status validation, direct Mongo update
```

**Analytics shows status usage (from `admin_service.py:93-94`):**
```python
for st in ["open", "in_progress", "pending_lawyer", "closed", "dismissed"]:
    cases_by_status[st] = await cases_col.count_documents({"status": st})
```

```mermaid
stateDiagram-v2
    [*] --> OPEN : create_case() — always created as OPEN
    Note on OPEN: status=CaseStatus.OPEN.value, lawyer_id=None
    
    OPEN --> PENDING_LAWYER : No lawyer assigned (lawyer_id=None)
    OPEN --> IN_PROGRESS : Lawyer assigned at creation
    Note on IN_PROGRESS: PATCH /cases/{id} with {lawyer_id, status:"in_progress"}
    
    PENDING_LAWYER --> IN_PROGRESS : PATCH /cases/{id} with lawyer_id
    Note on PENDING_LAWYER: status field unchanged, just lawyer_id set
    
    IN_PROGRESS --> CLOSED : PATCH /cases/{id} with {status:"closed"}
    IN_PROGRESS --> DISMISSED : PATCH /cases/{id} with {status:"dismissed"}
    
    CLOSED --> [*]
    DISMISSED --> [*]
```

---

## STD-2: Intake Step Progression — Exact Code Implementation

**Source:** `backend/app/services/intake_service.py`

**State Fields (from `intake_service.py:66-91`):**
```python
doc = {
    "current_step": 1,          # Integer 1-5
    "completed": False,        # Boolean
    "step1": None,             # Step data dict
    "step2": None,
    "step3": None,
    "step4": None,
    "step5": None,
    "case_id": None,           # Set after conversion
    "clarification_qa": [],    # AI Q&A for step 3
}
```

**Validation Rules (from `intake_service.py:16-22`):**
```python
STEP_REQUIRED_FIELDS = {
    1: ["province"],
    2: ["case_type", "urgency"],
    3: ["incident_description"],
    4: [],
    5: ["desired_outcome"],
}
```

**Step Save (from `intake_service.py:94-110`):**
```python
async def save_step(token: str, step: int, data: dict, client_id: str):
    _validate_step(step, data)  # Raises AppValidationError if missing fields
    await intake_repo.update_step(token, step, data)
    return {"session_token": token, "current_step": step, "completed": False}
```

**Conversion Check (from `intake_service.py:196-198`):**
```python
missing = [i for i in range(1, 6) if intake.get(f"step{i}") is None]
if missing:
    raise AppValidationError(f"Steps not completed: {missing}")
```

```mermaid
stateDiagram-v2
    [*] --> STEP_1 : start_intake()
    Note on STEP_1: current_step=1, completed=False, step1-5=None
    
    STEP_1 --> STEP_1 : ValidationError — province missing
    STEP_1 --> STEP_2 : save_step(1, data) ✓
    Note on STEP_2: step1={role, province, ...}
    
    STEP_2 --> STEP_2 : ValidationError — case_type/urgency missing
    STEP_2 --> STEP_3 : save_step(2, data) ✓
    Note on STEP_3: step2={case_type, urgency, ...}
    
    STEP_3 --> STEP_3 : ValidationError — incident_description missing
    STEP_3 --> STEP_3 : get_clarification() — AI Q&A loop
    STEP_3 --> STEP_4 : save_step(3, data) ✓
    Note on STEP_4: step3={incident_description, qa[]}
    
    STEP_4 --> STEP_4 : ValidationError (none possible — step 4 has no required fields)
    STEP_4 --> STEP_5 : save_step(4, data) ✓
    Note on STEP_5: step4={has_evidence?, evidence_description?, opposing_party?}
    
    STEP_5 --> STEP_5 : ValidationError — desired_outcome missing
    STEP_5 --> CONVERTING : save_step(5, data) ✓
    Note on CONVERTING: step5={desired_outcome, additional_notes?}
    
    CONVERTING --> COMPLETED : convert_to_case() success
    Note on COMPLETED: completed=True, case_id="ATT-{year}-{hex}"
    
    CONVERTING --> STEP_5 : AppValidationError — steps missing
    
    COMPLETED --> [*] : Redirect to /chat
```

---

## STD-3: Agreement Lifecycle — Exact Code Implementation

**Source:** `backend/app/services/agreement_service.py` + `backend/app/models/agreement.py`

**State Definition:**
```python
class AgreementStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
```

**Agreement Creation (from `agreement_service.py:17-51`):**
```python
async def create_agreement(title, body_html, parties, creator_id):
    doc = {
        "status": AgreementStatus.PENDING.value,  # ← Created as PENDING (not DRAFT!)
        "parties": [{"user_id": ..., "signed": False, ...} for p in parties],
        "eto_classification": None,
        "audit_log": [{"action": "created", ...}],
    }
```

**Signature Submission (from `agreement_service.py:66-121`):**
```python
async def submit_signature(agreement_id, user_id, method, signature_data, ip):
    # Guards:
    if agreement.get("status") == AgreementStatus.EXECUTED.value:
        raise AppValidationError("Agreement is already fully executed")
    if party already signed:
        raise AppValidationError("You have already signed this agreement")
    
    # Update signature
    await agreement_repo.update_party_signature(...)
    await agreement_repo.append_audit_log({"action": "signed", ...})
    
    # Check all signed
    all_signed = all(p.get("signed") for p in updated.get("parties", []))
    if all_signed:
        await agreement_repo.set_status(agreement_id, AgreementStatus.EXECUTED.value)
```

**ETO Classification (from `agreement_service.py:10-14`):**
```python
ETO_CLASSIFICATION = {
    SignatureMethod.CANVAS: "Advanced Electronic Signature (ETO 2002 S.2(d)(i))",
    SignatureMethod.TYPED: "Basic Electronic Signature (ETO 2002)",
    SignatureMethod.IMAGE_UPLOAD: "Basic Electronic Signature (ETO 2002)",
}
```

```mermaid
stateDiagram-v2
    [*] --> PENDING : create_agreement()
    Note on PENDING: status=PENDING.value (model default DRAFT is overridden!)
    
    PENDING --> PENDING : submit_signature() — partial (one party signed)
    Note on PENDING: parties[].signed = True for signing party, audit_log appended
    
    PENDING --> EXECUTED : submit_signature() — all parties signed
    Note on EXECUTED: all(p.get("signed") for p in parties) == True → set_status(EXECUTED)
    
    PENDING --> CANCELLED : Cancelled (not implemented in service)
    Note on CANCELLED: Would require DELETE or PATCH endpoint (not in current code)
    
    EXECUTED --> [*]
    CANCELLED --> [*]
```

---

## STD-4: Document Generation — Exact Code Implementation

**Source:** `backend/app/services/document_service.py`

**State Field:** `status: str = "pending"` — not an enum, just string literals

**Generation Flow (from `document_service.py:31-68`):**
```python
async def generate_document(case_id, client_id, template_type, fields):
    doc = {
        "status": "pending",  # ← Initial state
        "file_path": None,
        ...
    }
    await doc_repo.insert(doc)
    
    try:
        file_path = await _fill_template(doc_id, template_enum, fields)
        await doc_repo.update_file_path(doc_id, str(file_path))
        doc["file_path"] = str(file_path)
        doc["status"] = "generated"  # ← Success state
    except AppValidationError:
        await doc_repo.mark_failed(doc_id)
        doc["status"] = "failed"     # ← Failed state
        raise
    except Exception as exc:
        logger.error(...)
        await doc_repo.mark_failed(doc_id)
        doc["status"] = "failed"
    
    return doc
```

**Template Rendering (from `document_service.py:78-112`):**
```python
async def _fill_template(doc_id, template, fields):
    # 1. Validate template exists
    if not template_path.exists():
        raise AppValidationError(f"Template not found: {template.value}.docx")
    
    # 2. Render docx (thread pool)
    await asyncio.to_thread(_render)
    
    # 3. Convert to PDF via LibreOffice (thread pool)
    await asyncio.to_thread(subprocess.run, 
        ["libreoffice", "--headless", "--convert-to", "pdf", ...])
    
    # 4. Cleanup intermediate .docx
    output_docx.unlink(missing_ok=True)
    return output_pdf
```

```mermaid
stateDiagram-v2
    [*] --> pending : generate_document() starts
    Note on pending: doc inserted with status="pending", file_path=None
    
    pending --> generated : _fill_template() succeeds
    Note on generated: LibreOffice conversion OK, file_path set, status="generated"
    
    pending --> failed : AppValidationError (template missing)
    pending --> failed : docxtpl rendering exception
    pending --> failed : LibreOffice subprocess failure
    Note on failed: doc_repo.mark_failed(doc_id) called, status="failed"
    
    generated --> generated : get_document() — no change
    failed --> pending : Client retries (new generate_document() call)
    
    generated --> [*] : Document downloaded / abandoned
    failed --> [*] : Abandoned
```

---

## STD-5: Lawyer KYC Lifecycle — Exact Code Implementation

**Source:** `backend/app/services/admin_service.py` + `backend/app/models/user.py`

**State Fields (from `user.py:9-20`):**
```python
class LawyerProfile(BaseModel):
    bar_number: str | None = None
    kyc_verified: bool = False              # ← Main KYC state
    kyc_rejection_reason: str | None = None # ← Rejection detail
    rating: float = 0.0
    total_reviews: int = 0
    availability: bool = True
    specialization_embedding: list[float] | None = None
```

**Pending KYC Query (from `admin_service.py:18-27`):**
```python
async def list_pending_kyc() -> list[dict]:
    return await user_repo.find_many({
        "role": "lawyer",
        "lawyer_profile.kyc_verified": False,
        "lawyer_profile.bar_number": {"$ne": None},  # ← Has submitted docs
        "is_active": True,
    })
```

**KYC Approval (from `admin_service.py:35-52`):**
```python
if approved:
    await user_repo.update_one(
        {"_id": lawyer_id},
        {"$set": {
            "lawyer_profile.kyc_verified": True,
            "lawyer_profile.kyc_rejection_reason": None,  # ← Clear rejection
        }}
    )
    await create_notification(lawyer_id, NotificationType.KYC_APPROVED, ...)
    await send_kyc_result_email(lawyer["email"], approved=True)
```

**KYC Rejection (from `admin_service.py:53-69`):**
```python
else:
    await user_repo.update_one(
        {"_id": lawyer_id},
        {"$set": {
            "lawyer_profile.kyc_rejection_reason": reason or "Not specified",
            # ← kyc_verified stays FALSE
        }}
    )
    await create_notification(lawyer_id, NotificationType.KYC_REJECTED, ...)
```

**Derived State Logic:**
| State | Condition | Query |
|-------|-----------|-------|
| `REGISTERED` | `kyc_verified=False`, `bar_number=None` | New lawyer account |
| `PENDING_KYC` | `kyc_verified=False`, `bar_number!=None`, `is_active=True` | `list_pending_kyc()` |
| `VERIFIED_ACTIVE` | `kyc_verified=True` | Approved lawyer |
| `KYC_REJECTED` | `kyc_verified=False`, `kyc_rejection_reason!=None` | Rejected, needs resubmit |
| `SUSPENDED` | `is_active=False` | Account locked |

```mermaid
stateDiagram-v2
    [*] --> REGISTERED : POST /auth/register (role=LAWYER)
    Note on REGISTERED: lawyer_profile.kyc_verified=False, bar_number=None
    
    REGISTERED --> PENDING_KYC : Lawyer submits KYC (bar_number set)
    Note on PENDING_KYC: bar_number != None, kyc_verified=False, is_active=True
    Note on PENDING_KYC: Visible in GET /admin/kyc/pending
    
    PENDING_KYC --> VERIFIED_ACTIVE : process_kyc(approved=True)
    Note on VERIFIED_ACTIVE: kyc_verified=True, kyc_rejection_reason=None, KYC_APPROVED notification
    
    PENDING_KYC --> KYC_REJECTED : process_kyc(approved=False, reason)
    Note on KYC_REJECTED: kyc_rejection_reason set, kyc_verified stays False, KYC_REJECTED notification
    
    KYC_REJECTED --> PENDING_KYC : Lawyer resubmits (bar_number updated)
    Note on KYC_REJECTED: Same query as PENDING_KYC (kyc_verified=False + bar_number!=None)
    
    VERIFIED_ACTIVE --> SUSPENDED : is_active=False (admin action)
    
    SUSPENDED --> [*]
    VERIFIED_ACTIVE --> [*] : Account deleted
```

---

## STD-6: Notification State — Exact Code Implementation

**Source:** `backend/app/services/notification_service.py` + `backend/app/models/notification.py`

**State Fields (from `notification.py:9-21`):**
```python
class NotificationDocument(BaseModel):
    read: bool = False
    read_at: datetime | None = None
```

**Notification Types (from `constants.py:63-77`):**
```python
class NotificationType(str, Enum):
    CASE_UPDATE = "case_update"
    LAWYER_ASSIGNED = "lawyer_assigned"
    HEARING_SCHEDULED = "hearing_scheduled"
    DOCUMENT_READY = "document_ready"
    AGREEMENT_SIGNED = "agreement_signed"
    KYC_APPROVED = "kyc_approved"
    KYC_REJECTED = "kyc_rejected"
    REVIEW_RECEIVED = "review_received"
    APPOINTMENT_BOOKED = "appointment_booked"
    APPOINTMENT_CONFIRMED = "appointment_confirmed"
    APPOINTMENT_CANCELLED = "appointment_cancelled"
    APPOINTMENT_COMPLETED = "appointment_completed"
    APPOINTMENT_REMINDER = "appointment_reminder"
```

**Create Notification (from `notification_service.py:18-43`):**
```python
async def create_notification(user_id, type, title, body, payload=None):
    doc = {
        "read": False,           # ← Starts unread
        "read_at": None,
        ...
    }
    await notification_repo.insert(doc)
    # WebSocket push
    if _ws_manager:
        await _ws_manager.send_to_user(user_id, {"type": "notification", ...})
```

**Mark Read (from `notification_service.py:50-55`):**
```python
async def mark_read(notification_id: str, user_id: str) -> bool:
    return await notification_repo.mark_read(notification_id, user_id)
    # ← Repository sets read=True, read_at=datetime.utcnow()

async def mark_all_read(user_id: str) -> None:
    await notification_repo.mark_all_read(user_id)
```

```mermaid
stateDiagram-v2
    [*] --> UNREAD : create_notification()
    Note on UNREAD: read=False, read_at=None
    Note on UNREAD: WebSocket push: {type:"notification", title, body}
    
    UNREAD --> READ : mark_read(notification_id)
    Note on READ: read=True, read_at=datetime.utcnow()
    
    UNREAD --> READ : mark_all_read(user_id)
    Note on READ: Bulk update all user notifications
    
    READ --> [*]
```

---

## STD-7: AI Chat Session — Exact Code Implementation

**Source:** `backend/app/websockets/chat_socket.py` + `backend/app/models/chat.py`

**Message Types (from `chat_socket.py:143-191`):**
```python
# Server → Client
{"type": "thinking"}                                    # Processing started
{"type": "clarification", "question": "...", "matched_lawyers": []}  # Needs more info
{"type": "final", "content": "...", "citations": [], "confidence": 0.0}
{"type": "error", "content": "..."}

# Special: max_attempts reached
{"type": "final", "suggest_lawyer": True, "matched_lawyers": []}
```

**LangGraph State (from `chat_socket.py:38-84`):**
```python
state = {
    "needs_clarification": False,      # → triggers clarification response
    "clarification_question": "",
    "convergence_status": "pending",   # → "converged" | "max_attempts"
    "answer": "",
    "citations": [],
    "confidence": 0.0,
    "clarification_attempts": 0,
}
```

```mermaid
stateDiagram-v2
    [*] --> CONNECTED : WebSocket handshake
    Note on CONNECTED: chat_repo.find_by_session() or insert new session
    
    CONNECTED --> THINKING : receive_json() with content
    Note on THINKING: send_json({"type": "thinking"})
    
    THINKING --> CLARIFICATION_NEEDED : result["needs_clarification"]=True
    Note on CLARIFICATION_NEEDED: type="clarification", matched_lawyers[] included
    
    THINKING --> RESPONSE_COMPLETE : Normal flow
    Note on RESPONSE_COMPLETE: type="final", content, citations, confidence
    
    THINKING --> MAX_ATTEMPTS : convergence_status="max_attempts"
    Note on MAX_ATTEMPTS: type="final", suggest_lawyer=True, matched_lawyers[]
    
    THINKING --> ERROR : Exception in chat_graph.ainvoke()
    Note on ERROR: type="error", content="AI assistant is temporarily unavailable..."
    
    CLARIFICATION_NEEDED --> THINKING : User sends clarification answer
    RESPONSE_COMPLETE --> THINKING : User sends new message
    MAX_ATTEMPTS --> THINKING : User continues (or clicks "Connect with lawyer")
    ERROR --> THINKING : User retries
    
    CONNECTED --> DISCONNECTED : WebSocketDisconnect
    THINKING --> DISCONNECTED : Connection lost
    DISCONNECTED --> [*]
```

---

## Backend File Cross-Reference

| Diagram | Model File | Service/Socket File | Key State Fields |
|---------|------------|---------------------|------------------|
| STD-1 | `models/case.py` | `services/case_service.py` | `status: CaseStatus`, `lawyer_id: str\|None` |
| STD-2 | `models/intake.py` | `services/intake_service.py` | `current_step: int`, `completed: bool`, `step1-5: dict\|None` |
| STD-3 | `models/agreement.py` | `services/agreement_service.py` | `status: AgreementStatus`, `parties[].signed: bool` |
| STD-4 | `models/document.py` | `services/document_service.py` | `status: str` (pending/generated/failed), `file_path: str\|None` |
| STD-5 | `models/user.py` | `services/admin_service.py` | `lawyer_profile.kyc_verified: bool`, `lawyer_profile.kyc_rejection_reason: str\|None`, `is_active: bool` |
| STD-6 | `models/notification.py` | `services/notification_service.py` | `read: bool`, `read_at: datetime\|None` |
| STD-7 | `models/chat.py` | `websockets/chat_socket.py` | `messages[]`, `case_id`, `langgraph_checkpoint` |

---

> **Generated:** May 8, 2026  
> **From Code:** `backend/app/services/*.py`, `backend/app/websockets/*.py`, `backend/app/models/*.py`, `backend/app/core/constants.py`
