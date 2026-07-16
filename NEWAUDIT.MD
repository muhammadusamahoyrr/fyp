33  │ Family Settlement Generator   
23  │ Overseas Legal Guardian  
  These are the gaps that matter more than half the existing list:

  1. ★ Lawyer Verification & Trust Layer (CRITICAL, currently absent). Bar Council / Pakistan Bar enrollment
  verification, KYC, ratings, dispute history. In a low-trust market this is the entire foundation of a marketplace.
  Without it you are a directory of unverified strangers.
  2. ★ WhatsApp-Native Assistant (not import — the actual channel). A WhatsApp bot (Twilio/Meta Cloud API) that does
  Legal GPS, inheritance math, and notice generation inside the chat the user already lives in. This single decision
  changes your TAM from "people who install an app" to "everyone with a phone."
  3. Payment + Escrow + Consultation Booking. How does a user actually pay a lawyer? Video call? JazzCash/Easypaisa
  integration, escrow for consult fees, no-show handling. The revenue plumbing is missing entirely.
  4. Nikah Nama Builder & Reviewer (women's rights, huge). Column 18 (right to divorce/khula), mehr terms, conditions.
  Reviewing/negotiating the nikah nama before marriage is one of the highest-leverage women's-rights interventions in
  Pakistan and it's completely absent.
  5. Cybercrime / FIA Complaint Assistant. You have FIR but not the FIA NR3C / cybercrime pathway (blackmail,
  harassment, financial fraud online) — one of the fastest-growing complaint categories, especially for women.
  6. Maintenance (Nafqa) Calculator for women & children. Deterministic-ish, extremely common, pairs perfectly with your
  calculator strategy.
  7. Tenancy / Rent Agreement Generator + Rent Tribunal router. Enormous everyday demand; you route to it in Legal GPS
  but don't generate the instrument.
  8. Regional languages beyond Urdu. Pashto, Sindhi, Punjabi/Saraiki. The people most locked out of justice often don't
  read Urdu comfortably either. 
Opportunities For Overseas Pakistanis

  This is your single most monetizable segment and the docs underweight it (one feature, #23).

  - The pain is acute and the wallet is real. 9.6M diaspora, tens of billions in remittances, and property fraud against
  absentee owners is a genuine national scandal (fraudulent mutations, encroachment, fake POAs, tenant non-payment).
  - Build a full "Overseas Legal Desk" product line, not one feature:
    - Property-mutation monitoring + instant alerts (public-record polling).
    - Remote Power of Attorney generation + guidance on attestation at Pakistani consulates.
    - Vetted, verified local lawyer assignment with escrow (they can't shake hands to build trust — you are the trust).
    - Currency-friendly subscription (charge in USD/GBP/AED — where the willingness-to-pay actually is).
    - Time-zone-aware human concierge for high-value accounts.
  - Why it wins: these users have money, chronic anxiety about home-country assets, no physical presence, and no
  existing trustworthy product. This is where a Rs.-averse market becomes a $50–100/month subscriber. This segment alone
  could fund the free citizen-facing mission.

  ---
  Opportunities For Women And Vulnerable Groups

  The highest social-impact frontier — and currently thin in both docs.

  - Nikah Nama column-18 / mehr builder and reviewer — pre-marriage, the single most protective legal act a woman can
  take; almost no one uses it correctly.
  - Khula / divorce guided flow — demystify the process, generate the petition, route to family court/Union Council.
  - Maintenance (nafqa) calculator + demand letter — for wife and children; deterministic and high-frequency.
  - Cybercrime/blackmail complaint assistant (FIA) — online harassment and image-based abuse disproportionately hit
  women; a private, anonymous, no-login flow is life-changing.
  - Domestic-violence safety flow — anonymous, no-login (like SOS #11), routing to dar-ul-aman shelters,
  protection-order info, and the provincial DV act that actually applies (Sindh/Punjab differ — your Variance Engine
  shines here).
  - Inheritance enforcement for women — women are routinely denied their Faraid share. Your calculator + settlement
  generator + "here's your legal entitlement in rupees" is a quiet revolution.
  - Design constraints that matter: anonymous access, panic-exit/discreet UI, Urdu + regional voice input, and no
  requirement to name the abuser to get help. Vulnerable users abandon at the first login wall.

  Social-impact positioning: this is also your grant/NGO/CSR funding story and your press narrative. It costs little and
  differentiates enormously. 
  Combined across both docs — build/attention order, weighting impact × reach × revenue × feasibility:

  ┌──────┬─────────────────────────────────────────────┬────────┬──────────────────────────────────────────────────┐
  │ Rank │                   Feature                   │  Side  │                       Why                        │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  1   │ Urdu-First Legal Mode                       │  Both  │ Precondition for the entire market               │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  2   │ Legal GPS (routing)                         │  User  │ North star; solves wrong-forum epidemic          │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  3   │ Lawyer Verification / Trust Layer (missing) │  Both  │ Marketplace foundation; nothing works without it │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  4   │ Islamic Inheritance Calculator              │  User  │ #1 family conflict; deterministic trust anchor   │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  5   │ WhatsApp-Native Assistant (missing)         │  User  │ The distribution unlock; 100M+ TAM               │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  6   │ Case Law Oracle                             │ Lawyer │ Billion-dollar B2B monopoly seed                 │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  7   │ One-Click Lawyer Letter                     │  User  │ Turns a paid service free+instant                │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  8   │ FIR Without the Police                      │  User  │ Acute justice-failure fix                        │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  9   │ Salary Theft Calculator                     │  User  │ Deterministic, viral, shareable                  │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  10  │ Overseas Legal Guardian                     │  User  │ Highest-ARPU revenue engine                      │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  11  │ Multimodal Document Scanner                 │  Both  │ Kills literacy/digitization barrier              │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  12  │ Payment + Escrow + Booking (missing)        │  Both  │ The revenue plumbing                             │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  13  │ AI Second Chair                             │ Lawyer │ Replaces 2–3 days of junior work; retention      │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  14  │ Confidence + Citations Panel                │  User  │ Trust in AI legal output                         │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  15  │ Family Settlement Generator                 │  User  │ Diverts disputes from courts                     │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  16  │ Fee Note Generator                          │ Lawyer │ Recovers lost lawyer revenue; sticky B2B         │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  17  │ Nikah Nama / Maintenance flows (missing)    │  User  │ Highest women's-rights leverage                  │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  18  │ Hearing Prep Package + Legal Memo           │ Lawyer │ Daily-use B2B time savers                        │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  19  │ Human-in-the-Loop Quality Engine            │ Lawyer │ The only durable moat (data flywheel)            │
  ├──────┼─────────────────────────────────────────────┼────────┼──────────────────────────────────────────────────┤
  │  20  │ Government Form Autopilot                   │  User  │ Broad procedural pain; high effort, so later 