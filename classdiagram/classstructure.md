# ATTORNEY.AI — Class Structure

---

## 1. User *(Abstract Parent)*

| Section    | Members                                                                 |
|------------|-------------------------------------------------------------------------|
| **Attributes** | - id: String                                                       |
|            | - email: EmailStr                                                       |
|            | - password_hash: String                                                 |
|            | - full_name: String                                                     |
|            | - phone: String                                                         |
|            | - province: Province                                                    |
|            | - is_active: Boolean                                                    |
|            | - created_at: DateTime                                                  |
|            | - updated_at: DateTime                                                  |
| **Operations** | + register()                                                       |
|            | + login()                                                               |
|            | + resetPassword()                                                       |

---

## 2. Client *(extends User)*

| Section    | Members                                                                 |
|------------|-------------------------------------------------------------------------|
| **Attributes** | - preferred_lang: String                                           |
|            | - newsletter: Boolean                                                   |
| **Operations** | + submitIntake()                                                   |

---

## 3. Lawyer *(extends User)*

| Section    | Members                                                                 |
|------------|-------------------------------------------------------------------------|
| **Attributes** | - bar_number: String                                               |
|            | - rating: Float                                                         |
|            | - availability: Boolean                                                 |
|            | - specializations: List\<String\>                                       |
|            | - hourly_rate: Float                                                    |
|            | - years_of_experience: Integer                                          |
| **Operations** | + acceptCase()                                                     |
|            | + schedule()                                                            |

---

## 4. Admin *(extends User)*

| Section    | Members                                                                 |
|------------|-------------------------------------------------------------------------|
| **Attributes** | *(inherits all User attributes)*                                   |
| **Operations** | + approveKYC()                                                     |
|            | + manageUsers()                                                         |

---

## 5. CaseDocument

| Section    | Members                                                                 |
|------------|-------------------------------------------------------------------------|
| **Attributes** | - id: String                                                       |
|            | - case_number: String                                                   |
|            | - status: CaseStatus                                                    |
|            | - title: String                                                         |
|            | - milestones: List\<Milestone\>                                         |
|            | - client_id: String                                                     |
|            | - lawyer_id: String                                                     |
|            | - created_at: DateTime                                                  |
| **Operations** | + updateStatus()                                                   |
|            | + assignLawyer()                                                        |

---

## 6. IntakeDocument

| Section    | Members                                                                 |
|------------|-------------------------------------------------------------------------|
| **Attributes** | - id: String                                                       |
|            | - client_id: String                                                     |
|            | - dispute_type: String                                                  |
|            | - answers: JSON                                                         |
|            | - ai_summary: String                                                    |
|            | - status: IntakeStatus                                                  |
|            | - created_at: DateTime                                                  |
| **Operations** | + submit()                                                         |
|            | + convertToCase()                                                       |

---

## 7. AgreementDocument

| Section    | Members                                                                 |
|------------|-------------------------------------------------------------------------|
| **Attributes** | - id: String                                                       |
|            | - case_id: String                                                       |
|            | - created_by: String                                                    |
|            | - type: AgreementType                                                   |
|            | - content: String                                                       |
|            | - signed_at: DateTime                                                   |
|            | - status: AgreementStatus                                               |
| **Operations** | + sign()                                                           |
|            | + revoke()                                                              |

---

## 8. Document

| Section    | Members                                                                 |
|------------|-------------------------------------------------------------------------|
| **Attributes** | - id: String                                                       |
|            | - case_id: String                                                       |
|            | - client_id: String                                                     |
|            | - file_name: String                                                     |
|            | - file_url: String                                                      |
|            | - doc_type: DocType                                                     |
|            | - uploaded_at: DateTime                                                 |
| **Operations** | + upload()                                                         |
|            | + download()                                                            |
|            | + delete()                                                              |

---

## 9. Appointment

| Section    | Members                                                                 |
|------------|-------------------------------------------------------------------------|
| **Attributes** | - id: String                                                       |
|            | - client_id: String                                                     |
|            | - lawyer_id: String                                                     |
|            | - case_id: String                                                       |
|            | - date_time: DateTime                                                   |
|            | - duration: Integer                                                     |
|            | - status: AppointmentStatus                                             |
|            | - meeting_link: String                                                  |
| **Operations** | + book()                                                           |
|            | + cancel()                                                              |
|            | + reschedule()                                                          |

---

## 10. ChatSession

| Section    | Members                                                                 |
|------------|-------------------------------------------------------------------------|
| **Attributes** | - id: String                                                       |
|            | - client_id: String                                                     |
|            | - case_id: String                                                       |
|            | - started_at: DateTime                                                  |
|            | - status: SessionStatus                                                 |
| **Operations** | + startSession()                                                   |
|            | + endSession()                                                          |
|            | + sendMessage()                                                         |

---

## 11. Notification

| Section    | Members                                                                 |
|------------|-------------------------------------------------------------------------|
| **Attributes** | - id: String                                                       |
|            | - user_id: String                                                       |
|            | - content: String                                                       |
|            | - type: NotificationType                                                |
|            | - is_read: Boolean                                                      |
|            | - created_at: DateTime                                                  |
| **Operations** | + markAsRead()                                                     |
|            | + dismiss()                                                             |

---

## 12. Milestone *(Referenced by CaseDocument)*

| Section    | Members                                                                 |
|------------|-------------------------------------------------------------------------|
| **Attributes** | - id: String                                                       |
|            | - case_id: String                                                       |
|            | - title: String                                                         |
|            | - description: String                                                   |
|            | - due_date: DateTime                                                    |
|            | - completed: Boolean                                                    |
| **Operations** | + markComplete()                                                   |
|            | + updateDueDate()                                                       |

---

## Enumerations

```
enum Province       { PUNJAB, SINDH, KPK, BALOCHISTAN, ... }
enum CaseStatus     { PENDING, ACTIVE, CLOSED, APPEALED }
enum IntakeStatus   { DRAFT, SUBMITTED, CONVERTED }
enum AgreementType  { SETTLEMENT, FEE, MEDIATION }
enum AgreementStatus{ DRAFT, SIGNED, REVOKED }
enum DocType        { AFFIDAVIT, NOTICE, EVIDENCE, IDENTITY }
enum AppointmentStatus { SCHEDULED, COMPLETED, CANCELLED }
enum SessionStatus  { ACTIVE, ENDED }
enum NotificationType  { CASE_UPDATE, APPOINTMENT, KYC, AGREEMENT }
```
