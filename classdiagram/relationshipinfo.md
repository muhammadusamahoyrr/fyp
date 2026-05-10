# ATTORNEY.AI — Relationship Information

---

## A. Inheritance (Generalization) Relationships

| From     | To   | Type          | Symbol | Meaning                          |
|----------|------|---------------|--------|----------------------------------|
| Client   | User | Generalization | ——▷   | Client IS-A User                 |
| Lawyer   | User | Generalization | ——▷   | Lawyer IS-A User                 |
| Admin    | User | Generalization | ——▷   | Admin IS-A User                  |

All subclasses inherit: `id`, `email`, `password_hash`, `full_name`, `phone`, `province`, `is_active`, `created_at`, `updated_at`, `register()`, `login()`, `resetPassword()`

---

## B. Association Relationships

| From            | To               | Multiplicity | Label      | Meaning                                        |
|-----------------|------------------|--------------|------------|------------------------------------------------|
| Client          | IntakeDocument   | 1 → 0..*     | submits    | One client can submit many intake forms        |
| Client          | CaseDocument     | 1 → 0..*     | owns       | One client can own many cases                  |
| Lawyer          | CaseDocument     | 0..1 → 0..*  | handles    | Lawyer handles cases; may be unassigned        |
| IntakeDocument  | CaseDocument     | 1 → 0..1     | convertsTo | Intake may be converted to a formal case       |
| Client          | Appointment      | 1 → 0..*     | books      | Client books appointments                      |
| Lawyer          | Appointment      | 1 → 0..*     | hosts      | Lawyer hosts appointments                      |
| CaseDocument    | Appointment      | 1 → 0..*     | linkedTo   | Appointments tied to a legal case              |
| Client          | ChatSession      | 1 → 0..*     | starts     | Client initiates AI/legal chat sessions        |
| CaseDocument    | ChatSession      | 1 → 0..*     | attachedTo | Chat sessions linked to a specific case        |
| User            | Notification     | 1 → 0..*     | receives   | Any user (client/lawyer/admin) gets notices    |
| AgreementDocument | User           | 0..* → 1     | createdBy  | Agreement is created by a system user          |

---

## C. Composition Relationships (Strong Ownership)

| From         | To                | Multiplicity | Label    | Meaning                                             |
|--------------|-------------------|--------------|----------|-----------------------------------------------------|
| CaseDocument | AgreementDocument | 1 ◆→ 0..*   | contains | Agreements are owned by case; deleted with case     |
| CaseDocument | Milestone         | 1 ◆→ 0..*   | contains | Milestones belong to exactly one case               |

> **Composition (◆):** If the parent (CaseDocument) is deleted, all child objects are also deleted.

---

## D. Aggregation Relationships (Weak Ownership)

| From         | To       | Multiplicity | Label | Meaning                                              |
|--------------|----------|--------------|-------|------------------------------------------------------|
| CaseDocument | Document | 1 ◇→ 0..*   | has   | Case references documents; docs can exist alone      |
| Client       | Document | 1 ◇→ 0..*   | owns  | Client owns documents not tightly bound to one case  |

> **Aggregation (◇):** The child (Document) can exist independently of the parent.

---

## E. Summary Table

| # | Relationship               | Type          | Multiplicity | Symbol |
|---|----------------------------|---------------|--------------|--------|
| 1 | Client → User              | Generalization| —            | ——▷   |
| 2 | Lawyer → User              | Generalization| —            | ——▷   |
| 3 | Admin → User               | Generalization| —            | ——▷   |
| 4 | Client → IntakeDocument    | Association   | 1 → 0..*    | ——     |
| 5 | Client → CaseDocument      | Association   | 1 → 0..*    | ——     |
| 6 | Lawyer → CaseDocument      | Association   | 0..1 → 0..* | ——     |
| 7 | Intake → CaseDocument      | Association   | 1 → 0..1    | ——     |
| 8 | CaseDocument → Agreement   | Composition   | 1 → 0..*    | ◆——   |
| 9 | CaseDocument → Milestone   | Composition   | 1 → 0..*    | ◆——   |
|10 | CaseDocument → Document    | Aggregation   | 1 → 0..*    | ◇——   |
|11 | Client → Document          | Aggregation   | 1 → 0..*    | ◇——   |
|12 | Client → Appointment       | Association   | 1 → 0..*    | ——     |
|13 | Lawyer → Appointment       | Association   | 1 → 0..*    | ——     |
|14 | CaseDocument → Appointment | Association   | 1 → 0..*    | ——     |
|15 | Client → ChatSession       | Association   | 1 → 0..*    | ——     |
|16 | CaseDocument → ChatSession | Association   | 1 → 0..*    | ——     |
|17 | User → Notification        | Association   | 1 → 0..*    | ——     |
|18 | Agreement → User           | Association   | 0..* → 1    | ——     |

---

## F. Key Architectural Notes

- **User is abstract** — never instantiated directly. Always Client, Lawyer, or Admin.
- **IntakeDocument → CaseDocument** is the **AI pipeline trigger**: intake → AI processing → case creation.
- **Document vs AgreementDocument**: Documents are general files (aggregation); Agreements are case-specific (composition).
- **ChatSession** stores RAG memory, AI guidance history, and dispute context per case.
- **Milestone** is embedded within CaseDocument (composition) as the case timeline tracker.
