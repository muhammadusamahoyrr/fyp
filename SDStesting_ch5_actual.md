# Chapter 5: Testing and Evaluation

Attorney.AI delivers highly accurate and intelligent legal assistance through a sophisticated **Retrieval-Augmented Generation (RAG)** pipeline. Unlike generic AI, this system orchestrates a multi-stage workflow where multilingual legal queries (English/Urdu) are captured via Faster-Whisper STT, structured by a LangGraph-based orchestration agent, and then grounded in verified Pakistani legal statutes retrieved from a high-performance ChromaDB vector store. To ensure this complex architecture meets the highest standards of accuracy and security, rigorous testing has been conducted across all system modules.

## 5.1 Unit Testing
Unit testing verifies the smallest testable components of the software in isolation. In Attorney.AI, these tests ensure that the core data validation logic, security utilities, and algorithmic boosters perform as expected before they are integrated into the larger workflow.

### 5.1.1 Security and Data Validation Functions
**Unit Testing 1: CNIC Validation Function (`validate_cnic`)**
**Testing Objective**: To ensure the Pakistani CNIC validation correctly identifies 13-digit numeric formats without special characters, matching NADRA's database requirements.
**File Reference**: `backend/app/utils/validators.py`
**Logic Used**: `re.fullmatch(r"\d{13}", cnic)`

**Table 1: Unit Testing for CNIC Validation**

| No. | Test Case / Test Script | Attribute and Value | Expected Result | Actual Result | Result |
|-----|-------------------------|----------------------|-----------------|---------------|--------|
| 1   | Call `validate_cnic()` with valid CNIC | "3520112345678" | Returns True | Returns True | Pass |
| 2   | Call `validate_cnic()` with hyphen format | "35201-1234567-8" | Returns False | Returns False | Pass |
| 3   | Call `validate_cnic()` with short length | "12345" | Returns False | Returns False | Pass |
| 4   | Call `validate_cnic()` with alphanumeric | "35201-ABC-8" | Returns False | Returns False | Pass |

**Unit Testing 2: Password Strength Validation (`validate_password_strength`)**
**Testing Objective**: To verify that the password validation function correctly enforces the system's security policy (minimum 8 characters and at least one numeric digit).
**File Reference**: `backend/app/utils/validators.py`
**Logic Used**: `len(password) >= 8 and any(c.isdigit() for c in password)`

**Table 2: Unit Testing for Password Strength Validation**

| No. | Test Case / Test Script | Attribute and Value | Expected Result | Actual Result | Result |
|-----|-------------------------|----------------------|-----------------|---------------|--------|
| 1   | Validate strong password | "SecurePass123" | Returns True | Returns True | Pass |
| 2   | Validate password with only letters | "OnlyLetters" | Returns False | Returns False | Pass |
| 3   | Validate short password | "Abc1" | Returns False | Returns False | Pass |
| 4   | Validate empty string | "" | Returns False | Returns False | Pass |

**Unit Testing 3: Password Hashing and Verification**
**Testing Objective**: To ensure sensitive user credentials are securely hashed using Bcrypt (12 rounds) and correctly verified during login.
**File Reference**: `backend/app/core/security.py`

**Table 3: Unit Testing for Password Security**

| No. | Test Case / Test Script | Attribute and Value | Expected Result | Actual Result | Result |
|-----|-------------------------|----------------------|-----------------|---------------|--------|
| 1   | Generate Bcrypt Hash | "Client@1234" | Returns 60-char hash string | Returns hash | Pass |
| 2   | Verify correct password | plain="Client@1234", hash=Stored | Returns True | Returns True | Pass |
| 3   | Verify incorrect password | plain="WrongPass", hash=Stored | Returns False | Returns False | Pass |

### 5.1.2 AI Algorithmic Boosters
**Unit Testing 4: Specialization Boost Logic (`_specialization_boost`)**
**Testing Objective**: To verify that the matching engine correctly assigns scoring boosts for exact and related legal terms (e.g., matching "Bail" to "Criminal").
**File Reference**: `backend/app/services/lawyer_service.py`

**Table 4: Unit Testing for Specialization Boost**

| No. | Test Case / Test Script | Attribute and Value | Expected Result | Actual Result | Result |
|-----|-------------------------|----------------------|-----------------|---------------|--------|
| 1   | Exact Specialization Match | Spec=["criminal"], Case="criminal" | Returns 0.20 | Returns 0.20 | Pass |
| 2   | Related Term Match | Spec=["penal", "fir"], Case="criminal" | Returns 0.10 | Returns 0.10 | Pass |
| 3   | Unrelated Specialization | Spec=["family"], Case="criminal" | Returns 0.00 | Returns 0.00 | Pass |

## 5.2 Functional Testing
Functional testing evaluates the system's user-facing features through the UI or APIs to ensure they meet specified requirements.

### 5.2.1 Authentication and Access Control
**Functional Testing 1: Role-Based Dashboard Redirection**
**Testing Objective**: To ensure users are redirected to their respective environments (Client, Lawyer, Admin) after successful login.
**API Reference**: `POST /api/v1/auth/login`
**UI Reference**: Figure 1: Login Interface

**Table 5: Functional Testing for Authentication**

| No. | Test Case | Route / API | Expected Result | Actual Result | Result |
|-----|-----------|-------------|-----------------|---------------|--------|
| 1   | Admin Login | `auth/login` (admin) | Load `/admin` Dashboard | Dashboard loaded | Pass |
| 2   | Lawyer Login | `auth/login` (lawyer) | Load `/lawyer` Dashboard | Dashboard loaded | Pass |
| 3   | Client Login | `auth/login` (client) | Load `/dashboard` Overview | Dashboard loaded | Pass |

### 5.2.2 Legal Intake System
**Functional Testing 2: Multi-Step Legal Intake Wizard**
**Testing Objective**: To ensure the `ModIntake` component correctly collects and submits legal case data.
**API Reference**: `PATCH /api/v1/intake/{token}/step/{step}`
**UI Reference**: Figure 2: Legal Intake Wizard

**Table 6: Functional Testing for Legal Intake**

| No. | Test Case | API Endpoint | Expected Result | Actual Result | Result |
|-----|-----------|--------------|-----------------|---------------|--------|
| 1   | Submit Step 1 | `PATCH intake/{token}/step/1` | province: "punjab" saved | Data saved | Pass |
| 2   | Submit Step 2 | `PATCH intake/{token}/step/2` | case_type: "criminal" saved | Data saved | Pass |
| 3   | Convert Intake | `POST intake/{token}/convert` | New case created, status: "open" | Case created | Pass |

### 5.2.3 Administrative Management
**Functional Testing 3: Lawyer KYC Verification Flow**
**Testing Objective**: To ensure administrators can review and approve lawyer credentials in the `AdminKYCVerification` component.
**API Reference**: `POST /api/v1/admin/lawyers/{id}/verify`
**UI Reference**: Figure 3: Admin KYC Panel

**Table 7: Functional Testing for KYC Management**

| No. | Test Case | Action | Expected Result | Actual Result | Result |
|-----|-----------|--------|-----------------|---------------|--------|
| 1   | View Pending Lawyers | `GET admin/lawyers/pending` | List of unverified lawyers shown | List displayed | Pass |
| 2   | Approve Lawyer Profile | Verify Action: Approved | `kyc_verified` set to true in DB | DB updated | Pass |
| 3   | Reject Lawyer Profile | Verify Action: Rejected | Reason recorded, lawyer remains unverified | Status updated | Pass |

## 5.3 Business Rules Testing
Business rules testing uses decision table-based techniques to verify complex logical outcomes and security policies.

### 5.3.1 Decision Table 1: Lawyer Matching Scoring
**Business Rule**: The matching engine uses a multi-factor scoring algorithm (Semantic 50%, Spec 20%, Rating 15%, Availability 10%, Exp 5%).
**File Reference**: `backend/app/services/lawyer_service.py`

**Table 8: Decision Table for Lawyer Matching**

| Condition | Rule 1 | Rule 2 | Rule 3 | Rule 4 |
|-----------|--------|--------|--------|--------|
| Semantic Score > 0.60 (Strong) | Yes | No | Yes | No |
| Exact Specialization Match | Yes | Yes | No | No |
| Lawyer KYC Verified | Yes | Yes | Yes | No |
| Lawyer Availability Status | Yes | No | Yes | Yes |
| **Action: Resulting Match Rank** | **Top Recommended** | **Good Match** | **Partial Match** | **Unverified Match** |

### 5.3.2 Decision Table 2: API Rate Limiting (Security Rule)
**Business Rule**: Critical endpoints (Login, Register) must have rate limiting to prevent brute-force attacks.
**File Reference**: `backend/app/api/v1/routes/auth.py`

**Table 9: Decision Table for API Rate Limiting**

| Condition | Rule 1 | Rule 2 |
|-----------|--------|--------|
| Requests within 1 minute <= 5 | Yes | No |
| **Action: Request Status** | **Processed (200 OK)** | **Blocked (429 Too Many Requests)** |

## 5.4 Integration Testing
Integration testing focuses on the data flow and communication between interconnected system modules.

### 5.4.1 Integration Testing 1: AI-Powered Case Pipeline
**Testing Objective**: To verify the seamless transition of data from initial client intake to AI-structured case creation.
**Modules Involved**: `ModIntake`, `WhisperService`, `LangGraph Pipeline`, `ChromaDB`, `MongoDB`.

**Table 10: Integration Testing for Case Pipeline**

| No. | Test Step | Action / Interface | Expected Result | Actual Result | Result |
|-----|-----------|--------------------|-----------------|---------------|--------|
| 1 | Audio Intake | `POST /api/v1/voice/transcribe` | Whisper returns Urdu/English text | Text returned | Pass |
| 2 | AI Analysis | LangGraph orchestration | Extracted laws, summary, and risk JSON | JSON generated | Pass |
| 3 | Vector Storage | `CaseRepository.set_embedding` | Case vector indexed in ChromaDB | Indexed successfully | Pass |
| 4 | Auto-Matching | `match_lawyers_for_case` | Top 5 lawyers cached in MongoDB | Lawyers matched | Pass |

**Overall Result: Pass** - Complete data lifecycle from audio input to matched legal representation is verified.

### 5.4.2 Integration Testing 2: Appointment Lifecycle & Notifications
**Testing Objective**: To verify the bi-directional data flow between Client booking and Lawyer management.
**Modules Involved**: `AppointmentsPage`, `AppointmentRepository`, `NotificationService`, `WebSockets`.

**Table 11: Integration Testing for Appointments**

| No. | Test Step | Action / Interface | Expected Result | Actual Result | Result |
|-----|-----------|--------------------|-----------------|---------------|--------|
| 1 | Book Appointment | `POST /api/v1/appointments` | New `pending` appointment in MongoDB | Record created | Pass |
| 2 | Notify Lawyer | WebSocket → `APPOINTMENT_BOOKED` | Real-time event in Lawyer dashboard | UI updated live | Pass |
| 3 | Confirm Appointment | `POST /api/v1/appointments/{id}/confirm` | Status → `confirmed`, Client notified | Status updated | Pass |

**Overall Result: Pass** - Bi-directional communication between Client and Lawyer via WebSockets and DB is functional.
