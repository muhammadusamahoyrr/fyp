# Attorney.AI — Sequence Diagrams (4)
> All endpoints, field names, validation rules, response shapes, and logic are sourced directly from the backend source code.

---

## SD-1 — Legal Query Intake & AI Case Structuring (M2 + M3)

**Modules:** M2 (Legal Intake) + M3 (AI Legal Guidance)

**Key source files:**
- `backend/app/services/intake_service.py`
- `backend/app/api/v1/routes/intake.py`
- `backend/app/services/case_service.py`
- `backend/app/websockets/chat_socket.py`
- `frontend/src/components/client/ModIntake.jsx`
- `frontend/src/components/client/ModChatbot.jsx`
- `frontend/src/components/shared/CaseContext.jsx`

```mermaid
sequenceDiagram
    participant U  as Client (Browser)
    participant FE as ModIntake.jsx
    participant CTX as CaseContext.jsx
    participant API as FastAPI /api/v1
    participant IS  as intake_service.py
    participant CS  as case_service.py
    participant DB  as MongoDB
    participant WS  as WebSocket /ws/chat/{session_id}
    participant CH  as chat_socket.py
    participant CR  as chat_repo (MongoDB)

    rect rgb(235, 245, 255)
        Note over U,DB: ── PHASE 1 : M2  Legal Intake (5 Steps) ──

        U->>FE: Opens /intake
        FE->>API: POST /intake/start
        Note over API: require_client guard (JWT)
        API->>IS: start_intake(client_id)
        IS->>DB: Insert Intake {current_step:1, completed:false,<br/>step1-5: null, ai_structured_case.summary:"pending"}
        DB-->>IS: intake saved
        IS-->>API: {session_token, message:"Intake session started"}
        API-->>FE: {session_token}
        Note over FE: Token stored for all PATCH calls

        Note over U,FE: Step 1 — Role + Province
        U->>FE: Select role (Plaintiff | Defendant) + select province
        FE->>API: PATCH /intake/{token}/step/1  body:{data:{province}}
        API->>IS: save_step(token, 1, data, client_id)
        IS->>IS: _validate_step(1) — required:[province]
        IS->>DB: Update Intake.step1 = {role, province}
        DB-->>IS: OK
        IS-->>API: {session_token, current_step:1, completed:false, case_id:null}
        API-->>FE: Step 1 saved

        Note over U,FE: Step 2 — Case Type + Urgency
        U->>FE: Choose case_type (CIVIL/CRIMINAL/CONSTITUTIONAL/FAMILY) + urgency
        FE->>API: PATCH /intake/{token}/step/2  body:{data:{case_type, urgency}}
        API->>IS: save_step(token, 2, data, client_id)
        IS->>IS: _validate_step(2) — required:[case_type, urgency]
        IS->>DB: Update Intake.step2
        IS-->>API: {current_step:2, completed:false}
        API-->>FE: Step 2 saved

        Note over U,FE: Step 3 — Incident Description (AI Follow-up Questions)
        U->>FE: Describe incident (text or voice) — answer AI follow-up questions
        FE->>API: PATCH /intake/{token}/step/3  body:{data:{incident_description, incident_date, incident_location}}
        API->>IS: save_step(token, 3, data, client_id)
        IS->>IS: _validate_step(3) — required:[incident_description]
        IS->>DB: Update Intake.step3
        IS-->>API: {current_step:3, completed:false}
        API-->>FE: Step 3 saved

        Note over U,FE: Step 4 — Evidence Info (optional fields)
        U->>FE: Fill evidence details (optional: has_evidence, opposing_party)
        FE->>API: PATCH /intake/{token}/step/4  body:{data:{has_evidence, evidence_description, opposing_party}}
        API->>IS: save_step(token, 4, data, client_id)
        IS->>IS: _validate_step(4) — required:[] (no required fields)
        IS->>DB: Update Intake.step4
        IS-->>API: {current_step:4, completed:false}
        API-->>FE: Step 4 saved

        Note over U,FE: Step 5 — Desired Outcome + Categorization
        U->>FE: State desired outcome + select case category
        FE->>API: PATCH /intake/{token}/step/5  body:{data:{desired_outcome, additional_notes}}
        API->>IS: save_step(token, 5, data, client_id)
        IS->>IS: _validate_step(5) — required:[desired_outcome]
        IS->>DB: Update Intake.step5
        IS-->>API: {current_step:5, completed:false}
        API-->>FE: Step 5 saved — all steps complete

        Note over U,FE: Submit — Convert Intake to Case
        U->>FE: Click "Submit Case"
        FE->>API: POST /intake/{token}/convert
        API->>IS: convert_to_case(token, client_id)
        IS->>DB: Fetch intake by token
        DB-->>IS: Full intake document
        IS->>IS: Validate: all step1-5 present<br/>(else AppValidationError "Steps not completed:[n]")
        IS->>CS: create_case(client_id, {case_type:step2.case_type, province:step1.province,<br/>title:step3.incident_description[:80], description:step3.incident_description, intake_id})
        CS->>DB: Insert Case {case_number:"ATT-{year}-{hex}", status:"open",<br/>lawyer_id:null, milestones:[], hearing_dates:[], case_embedding:null}
        DB-->>CS: case_id
        CS-->>IS: Case document
        Note over IS: TODO: trigger ai_structured_case async processing
        IS->>DB: Mark Intake {completed:true, case_id}
        IS-->>API: {session_token, completed:true, case_id}
        API-->>FE: {case_id}
        FE->>CTX: completeIntake({role, caseType, caseSubtype, description, evidenceDocs})
        Note over CTX: intakeDone=true, caseRef set
        FE-->>U: Redirect to /chat
    end

    rect rgb(235, 255, 240)
        Note over U,CR: ── PHASE 2 : M3  AI Legal Guidance (Chat) ──

        U->>FE: Opens /chat (case context loaded from CaseContext)
        Note over FE: ModChatbot mounts — session_id generated
        FE->>WS: WebSocket connect: ws://…/ws/chat/{session_id}?token=JWT
        WS->>CH: Handshake — decode_token(token)
        alt Token invalid
            CH-->>FE: close(code=4001)
        else Token valid
            CH->>CR: find_by_session(session_id)
            alt Session does not exist
                CR-->>CH: null
                CH->>CR: Insert ChatSession {session_id, client_id, case_id:null,<br/>messages:[], langgraph_checkpoint:null}
            end
            CH-->>FE: Connection accepted
            FE-->>U: Chat ready — greeting shown (time-based: Morning/Afternoon/Evening)

            U->>FE: Type query (EN or UR) + click Send
            Note over FE: typing=true; msg added to msgs[] {role:"user", text, time}
            FE->>WS: send({content, case_id, case_type, province})

            WS->>CH: receive_json(data)
            CH->>CR: append_message(session_id, {role:"user", content,<br/>citations:[], confidence:null, created_at})
            CH->>CR: update_session_meta(session_id, {case_id, case_type, province})

            Note over CH: TODO: invoke LangGraph supervisor + stream tokens
            Note over CH: Currently returns stub response

            CH->>WS: send_json({type:"final", content:"AI legal assistant is not yet connected.<br/>Your query has been recorded.", citations:[], confidence:0.0})
            WS-->>FE: Final response message
            Note over FE: typing=false; msg added {role:"ai", text, refs:citations}
            FE-->>U: AI response displayed

            CH->>CR: append_message(session_id, {role:"assistant", content,<br/>citations:[], confidence:0.0, created_at})
        end
    end
```

---

## SD-2 — Lawyer Discovery & Appointment Booking (M4)

**Module:** M4 (Lawyer Discovery)

**Key source files:**
- `backend/app/services/lawyer_service.py`
- `backend/app/api/v1/routes/lawyers.py`
- `backend/app/services/case_service.py`
- `backend/app/services/notification_service.py`
- `frontend/src/components/shared/CaseContext.jsx`

**Note on matching algorithm (current implementation):**
`match_score = (rating / 5.0) × 0.5  +  (0.2 if availability else 0)  +  0.3`
The `0.3` is a static placeholder — `TODO: replace with cosine_similarity(case_embedding, lawyer_embedding) × 0.5` once AI phase is integrated.

**Note on appointment booking:** No dedicated `/appointments` endpoint exists. Appointment confirmation is handled via `CaseContext.confirmAppointment()` in frontend state. Case assignment is persisted via `PATCH /cases/{case_id}`.

```mermaid
sequenceDiagram
    participant U   as Client (Browser)
    participant FE  as ModLawyers.jsx
    participant CTX as CaseContext.jsx
    participant API as FastAPI /api/v1
    participant LS  as lawyer_service.py
    participant CaS as case_service.py
    participant NS  as notification_service.py
    participant DB  as MongoDB
    participant L   as Lawyer (Browser)

    rect rgb(255, 248, 235)
        Note over U,DB: ── PHASE 1 : Discover Lawyers ──

        U->>FE: Opens /lawyers  (case_id in CaseContext)
        FE->>API: GET /lawyers/match/{case_id}
        Note over API: require_client guard (JWT)
        API->>LS: match_lawyers_for_case(case_id)
        LS->>DB: case_repo.find_by_id(case_id)
        DB-->>LS: {case_type, province, …}

        LS->>DB: user_repo.find_lawyers(province, case_type,<br/>min_rating=0.0, page=1, page_size=20)
        Note over DB: Filters: role=lawyer, kyc_verified=true,<br/>province match, case_type match
        DB-->>LS: Up to 20 lawyer profiles

        LS->>LS: Score each lawyer:<br/>rating_score = (rating / 5.0) × 0.5<br/>avail_score  = 0.2 if availability else 0.0<br/>match_score  = rating_score + avail_score + 0.3
        Note over LS: Sorted descending by match_score — top 5 returned
        LS->>LS: scored.sort(reverse=True) → return scored[:5]

        LS-->>API: [{lawyer_id, name, match_score,<br/>lawyer_profile:{specialization, rating, availability}, …}]
        API-->>FE: Top 5 matched lawyers
        FE-->>U: Lawyer cards rendered (sorted by match score)

        opt Client wants to manually filter
            U->>FE: Apply filters (province, case_type, min_rating, availability)
            FE->>API: GET /lawyers?province=&case_type=&min_rating=&availability=&page=1
            API->>LS: search_lawyers(province, case_type, min_rating, availability, page, page_size)
            LS->>DB: user_repo.find_lawyers(…filters…)
            DB-->>LS: Paginated lawyer list
            LS-->>API: Paginated result (passwords/CNIC stripped by _sanitize)
            API-->>FE: Filtered results
            FE-->>U: Updated lawyer list
        end
    end

    rect rgb(235, 255, 248)
        Note over U,L: ── PHASE 2 : Select Lawyer & Book Appointment ──

        U->>FE: Click lawyer card to view profile
        FE->>CTX: selectLawyer(lawyer)
        Note over CTX: selectedLawyer = lawyer (full object stored)

        U->>FE: Click "Book Appointment"
        FE-->>U: Show appointment modal (date, time, details fields)

        U->>FE: Fill {date, time, details} + click "Confirm"
        FE->>CTX: confirmAppointment({date, time, details})
        CTX->>CTX: milestoneId = "appt-{Date.now()}"
        CTX->>CTX: Create milestone {id:milestoneId, status:"active",<br/>event:"Consultation — {lawyer.name}", date, time,<br/>desc:details, tag:"appointment"}
        CTX->>CTX: Update state {appointment:{date, time, details, status:"confirmed"},<br/>appointmentMilestones:[…, milestone]}
        Note over CTX: Module 7 (Tracking) reads appointmentMilestones<br/>from context — timeline updates immediately

        FE->>API: PATCH /cases/{case_id}  body:{lawyer_id, status:"in_progress"}
        Note over API: get_current_user guard (any role)
        API->>CaS: update_case(case_id, {lawyer_id, status:"in_progress"}, requester_id, role)
        CaS->>DB: case_repo.find_by_id(case_id)
        DB-->>CaS: Case document
        CaS->>CaS: _assert_access — client_id match check
        CaS->>DB: case_repo.update_one({$set:{lawyer_id, status:"in_progress", updated_at}})
        DB-->>CaS: Updated case
        CaS-->>API: Updated Case document
        API-->>FE: {case_id, status:"in_progress", lawyer_id}
        FE-->>U: Appointment confirmed — "Consultation booked"

        API->>NS: create_notification(lawyer_id, LAWYER_ASSIGNED,<br/>"New case assigned", "Client booked a consultation")
        NS->>DB: Insert Notification {user_id:lawyer_id, type:"lawyer_assigned",<br/>read:false, read_at:null}
        NS->>NS: _ws_manager.send_to_user(lawyer_id,<br/>{type:"notification", title:"New case assigned", body:"…"})
        NS-->>L: WebSocket push — "New case assigned"
    end
```

---

## SD-3 — Digital Agreement & E-Signing Workflow (M5)

**Module:** M5 (Digital Agreements & E-Signing)

**Key source files:**
- `backend/app/services/agreement_service.py`
- `backend/app/api/v1/routes/agreements.py`
- `backend/app/services/notification_service.py`
- `backend/app/core/constants.py`  (AgreementStatus, SignatureMethod)

**ETO 2002 classifications (from `ETO_CLASSIFICATION` dict in service):**
- `CANVAS` → `"Advanced Electronic Signature (ETO 2002 S.2(d)(i))"`
- `TYPED` → `"Basic Electronic Signature (ETO 2002)"`
- `IMAGE_UPLOAD` → `"Basic Electronic Signature (ETO 2002)"`

**Guards enforced by `submit_signature()`:**
1. User must be listed in `agreement.parties`
2. `agreement.status` must **not** be `EXECUTED`
3. That specific party must not have already signed

```mermaid
sequenceDiagram
    participant C   as Client (Browser)
    participant L   as Lawyer (Browser)
    participant FE  as ModAgreements.jsx
    participant API as FastAPI /api/v1
    participant AS  as agreement_service.py
    participant NS  as notification_service.py
    participant DB  as MongoDB

    rect rgb(245, 235, 255)
        Note over C,DB: ── PHASE 1 : Create Agreement ──

        C->>FE: Opens /agreements — clicks "New Agreement"
        FE-->>C: Agreement editor (TipTap / Quill rich-text)
        C->>FE: Fill title, draft body_html (terms), add parties

        FE->>API: POST /agreements<br/>body:{title, body_html, party_ids:[{user_id, full_name}, …]}
        Note over API: get_current_user guard (any authenticated user)
        API->>AS: create_agreement(title, body_html, parties, creator_id)
        AS->>DB: Insert Agreement {<br/>  status: "pending",<br/>  parties:[{user_id, full_name, signed:false,<br/>            signed_at:null, signature_method:null, signature_data:null}],<br/>  eto_classification: null,<br/>  audit_log:[{action:"created", actor_id:creator_id, timestamp}],<br/>  created_by:creator_id<br/>}
        DB-->>AS: agreement_id
        AS-->>API: Full agreement document
        API-->>FE: {agreement_id, status:"pending", parties:[…]}
        FE-->>C: Agreement created — status PENDING
        Note over FE: Both parties see agreement via GET /agreements/{id}
    end

    rect rgb(235, 255, 255)
        Note over C,DB: ── PHASE 2 : Client Signs ──

        C->>FE: Opens agreement — reviews terms
        FE->>API: GET /agreements/{agreement_id}
        API->>AS: get_agreement(agreement_id, requester_id)
        AS->>DB: find_by_id(agreement_id)
        DB-->>AS: Agreement document
        AS->>AS: Check requester in party_ids OR is creator
        AS-->>API: Agreement document
        API-->>FE: Agreement + parties sign status
        FE-->>C: Show agreement body + signature panel

        C->>FE: Choose signature method
        alt Canvas Draw Pad
            C->>FE: Draws signature on canvas
            Note over FE: method = "canvas"
        else Typed Name
            C->>FE: Types full legal name
            Note over FE: method = "typed"
        else Image Upload (PNG / JPG)
            C->>FE: Uploads signature image
            Note over FE: method = "image_upload"
        end

        FE->>API: POST /agreements/{agreement_id}/sign<br/>body:{method, signature_data}
        Note over API: IP captured — request.client.host
        API->>AS: submit_signature(agreement_id, client_id, method, signature_data, ip)

        AS->>DB: find_by_id(agreement_id)
        DB-->>AS: Agreement
        AS->>AS: Guard 1 — client_id in party_ids? (else ForbiddenError)
        AS->>AS: Guard 2 — status != "executed"? (else AppValidationError)
        AS->>AS: Guard 3 — client not already signed? (else AppValidationError)

        AS->>AS: eto = ETO_CLASSIFICATION[method]
        AS->>DB: update_party_signature(agreement_id, client_id, {method, data})
        AS->>DB: append_audit_log({action:"signed", actor_id:client_id,<br/>timestamp, ip_address, note:eto})
        AS->>DB: update_one($set:{eto_classification:eto})

        AS->>DB: Re-fetch agreement → check all parties signed?
        DB-->>AS: Updated agreement (lawyer.signed still false)
        AS->>AS: all_signed = false — NOT yet fully executed
        AS-->>API: Updated agreement document
        API-->>FE: {status:"pending", parties:[{client:signed:true}, {lawyer:signed:false}]}
        FE-->>C: "Waiting for co-signer"

        API->>NS: create_notification(lawyer_id, AGREEMENT_SIGNED,<br/>"Agreement awaiting your signature", title)
        NS->>DB: Insert Notification {read:false}
        NS-->>L: WebSocket push: {type:"notification", title:"Agreement awaiting your signature"}
    end

    rect rgb(255, 245, 235)
        Note over L,DB: ── PHASE 3 : Lawyer Signs → Auto-Execute ──

        L->>FE: Opens agreement from notification
        FE->>API: GET /agreements/{agreement_id}
        API-->>FE: Agreement (client already signed)
        FE-->>L: Show terms + client signature confirmed

        L->>FE: Choose signature method + sign
        FE->>API: POST /agreements/{agreement_id}/sign<br/>body:{method, signature_data}
        API->>AS: submit_signature(agreement_id, lawyer_id, method, signature_data, ip)

        AS->>DB: find_by_id + run all 3 guards
        DB-->>AS: Agreement passes guards
        AS->>AS: eto = ETO_CLASSIFICATION[method]
        AS->>DB: update_party_signature(agreement_id, lawyer_id, {method, data})
        AS->>DB: append_audit_log({action:"signed", actor_id:lawyer_id, …, note:eto})
        AS->>DB: update_one($set:{eto_classification:eto})

        AS->>DB: Re-fetch agreement
        DB-->>AS: Both parties now signed:true
        AS->>AS: all_signed = all(p["signed"] for p in parties) → True
        AS->>DB: agreement_repo.set_status(agreement_id, "executed")
        Note over DB: Agreement status → EXECUTED<br/>Legally binding under ETO 2002

        AS-->>API: Fully executed agreement
        API-->>FE: {status:"executed", parties:[all signed]}
        FE-->>L: "Agreement fully executed" + download option

        API->>NS: create_notification(client_id, AGREEMENT_SIGNED,<br/>"Agreement fully executed", title)
        NS-->>C: WebSocket push: {type:"notification", title:"Agreement fully executed"}
    end
```

---

## SD-4 — Document Automation & AI Drafting (M6)

**Module:** M6 (Document Automation & Drafting)

**Key source files:**
- `backend/app/services/document_service.py`
- `backend/app/api/v1/routes/documents.py`
- `backend/app/services/notification_service.py`

**Template files location:** `knowledge_base/templates/{template_type}.docx`
**Generated files location:** `backend/app/uploads/docs/{doc_id}.pdf`

**Available templates (from `TEMPLATE_TITLES` dict):**
| `template_type` value | Title |
|---|---|
| `plaint_civil` | Civil Plaint |
| `written_statement` | Written Statement |
| `legal_notice` | Legal Notice |
| `nda` | Non-Disclosure Agreement |
| `rental_agreement` | Rental Agreement |

**Important — `fields` parameter:** Client currently provides the `fields` dict manually in the request body. The line `# TODO: AI — replace fields dict with LLM extraction from case data` is present in `document_service.py` — LLM auto-extraction is a planned AI-phase feature.

**Error handling (two distinct paths):**
- `AppValidationError` (e.g. template file missing) → `mark_failed()` + **re-raises** → 422 response to client
- Any other `Exception` (e.g. LibreOffice crash) → `mark_failed()` + **logged**, does **not** re-raise → returns doc with `status:"failed"`

```mermaid
sequenceDiagram
    participant U   as Client (Browser)
    participant FE  as ModDocuments.jsx
    participant API as FastAPI /api/v1
    participant DS  as document_service.py
    participant TPL as docxtpl (thread pool)
    participant LO  as LibreOffice --headless (thread pool)
    participant FS  as File System (uploads/docs/)
    participant NS  as notification_service.py
    participant DB  as MongoDB

    U->>FE: Opens /documents
    FE-->>U: Template picker (Civil Plaint / Legal Notice / NDA / …)

    U->>FE: Select template type
    U->>FE: Fill document fields (plaintiff, defendant, facts, relief_sought, …)
    Note over FE: fields dict built from form inputs<br/>(TODO: replaced by LLM extraction in AI phase)

    U->>FE: Click "Generate Document"
    FE->>API: POST /documents/generate<br/>body:{case_id, template_type, fields:{…}}
    Note over API: get_current_user guard (JWT)

    API->>DS: generate_document(case_id, client_id, template_type, fields)
    DS->>DB: case_repo.find_by_id(case_id)
    DB-->>DS: Case document (or NotFoundError)

    DS->>DS: template_enum = DocumentTemplate(template_type)
    DS->>DB: doc_repo.insert({_id:doc_id, case_id, client_id,<br/>template_type, title:TEMPLATE_TITLES[template],<br/>fields, file_path:null, status:"pending", created_at})
    DB-->>DS: doc_id confirmed
    Note over FE: status = "pending" — generation starts

    DS->>DS: Call _fill_template(doc_id, template_enum, fields)

    DS->>FS: Check template_path exists:<br/>knowledge_base/templates/{template_type}.docx
    alt Template file missing
        FS-->>DS: File not found
        DS->>DS: raise AppValidationError
        DS->>DB: doc_repo.mark_failed(doc_id)
        DB-->>DS: status="failed"
        DS-->>API: AppValidationError (re-raised)
        API-->>FE: 422 Unprocessable Entity
        FE-->>U: "Template not available — please try another"
    else Template exists
        FS-->>DS: template_path valid

        DS->>FS: UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

        DS->>TPL: asyncio.to_thread(_render)<br/>DocxTemplate(template_path).render(fields).save(doc_id.docx)
        Note over TPL: CPU-bound — runs in thread pool to avoid blocking event loop
        alt docxtpl rendering fails
            TPL-->>DS: Exception
            DS->>DB: doc_repo.mark_failed(doc_id)
            DS-->>API: doc {status:"failed"} — does NOT re-raise
            API-->>FE: {doc_id, status:"failed"}
            FE-->>U: "Generation failed — please retry"
        else Rendering succeeds
            TPL-->>DS: doc_id.docx saved to uploads/docs/

            DS->>LO: asyncio.to_thread(subprocess.run,<br/>["libreoffice","--headless","--convert-to","pdf",<br/>"--outdir", UPLOADS_DIR, doc_id.docx], check=True)
            Note over LO: Slow blocking call — thread pool prevents FastAPI freeze
            alt LibreOffice fails (subprocess non-zero exit)
                LO-->>DS: CalledProcessError
                DS->>DS: logger.error("Document generation failed …")
                DS->>DB: doc_repo.mark_failed(doc_id)
                DS-->>API: doc {status:"failed"}
                API-->>FE: {doc_id, status:"failed"}
                FE-->>U: "PDF conversion failed — please retry"
            else Conversion succeeds
                LO-->>DS: doc_id.pdf written to uploads/docs/
                DS->>FS: output_docx.unlink(missing_ok=True)
                Note over FS: Intermediate .docx deleted — only PDF kept

                DS->>DB: doc_repo.update_file_path(doc_id, "uploads/docs/doc_id.pdf")
                DS->>DS: doc["status"] = "generated"
                DS-->>API: {doc_id, title, template_type,<br/>file_path:"uploads/docs/doc_id.pdf", status:"generated"}
                API-->>FE: {doc_id, status:"generated"}
                FE-->>U: "Document ready — Download PDF" button enabled

                API->>NS: create_notification(client_id, DOCUMENT_READY,<br/>"Document ready", title)
                NS->>DB: Insert Notification {read:false}
                NS-->>U: WebSocket push: {type:"notification", title:"Document ready"}
            end
        end
    end

    Note over U,DB: ── Download ──
    U->>FE: Click "Download PDF"
    FE->>API: GET /documents/{doc_id}/download
    API->>DS: get_document(doc_id, requester_id)
    DS->>DB: doc_repo.find_by_id(doc_id)
    DB-->>DS: Document record
    DS->>DS: Verify doc.client_id == requester_id (else NotFoundError)
    DS-->>API: Document with file_path
    API->>API: Check Path(file_path).exists() on disk<br/>(else NotFoundError "Document file")
    API-->>FE: FileResponse(path, media_type="application/pdf",<br/>filename="{title}.pdf")
    FE-->>U: PDF download starts in browser
```
