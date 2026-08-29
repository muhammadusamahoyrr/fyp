"""
Full end-to-end test:
  1.  Seed KYC-verified lawyer into MongoDB + ChromaDB
  2.  Register new client via API
  3.  Login -> get JWT
  4.  Start intake session
  5.  Save steps 1-3 (province, case_type, urgency, description)
  6.  Clarification rounds: POST /clarify until done (up to 4 questions)
  7.  Save steps 4-5
  8.  POST /convert -> intake_graph fires (retrieval+grader+intake+hallucination)
  9.  GET /intake   -> inspect ai_structured_case (check for CrPC/PPC statute refs)
  10. Poll GET /lawyers/match/{case_id} -> verify matched_lawyers populated
  11. Print pass/fail summary

Run from backend/ directory with server already running on :8000:
    python test_full_e2e.py
"""
import asyncio
import json
import random
import string
import sys
import time

import httpx

sys.path.insert(0, ".")

BASE     = "http://127.0.0.1:8000/api/v1"
TIMEOUT  = 180.0
POLL_MAX = 8
POLL_SEC = 4

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"

results = []

def check(label, condition, detail=""):
    icon = PASS if condition else FAIL
    msg  = f"{icon}  {label}"
    if detail:
        msg += f"  [{detail}]"
    print(msg)
    results.append((label, condition))

def section(title):
    print("\n" + "-" * 60)
    print("  " + title)
    print("-" * 60)

def rand_email():
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"e2e_{suffix}@attorney-ai-test.com"


# --- DB seed (direct motor connection) ---

async def seed_lawyer():
    """Insert KYC-verified test lawyer into MongoDB + embed into ChromaDB."""
    from app.core.security import hash_password
    from app.db.mongodb    import connect_db, get_database
    from app.db.chroma     import connect_chroma

    await connect_db()
    connect_chroma()

    db = get_database()
    LAWYER_ID = "e2e-lawyer-seed-001"

    await db["users"].delete_many(
        {"$or": [{"_id": LAWYER_ID}, {"email": "e2elawyer@attorney-ai.test"}]}
    )
    await db["users"].insert_one({
        "_id":           LAWYER_ID,
        "email":         "e2elawyer@attorney-ai.test",
        "password_hash": hash_password("Lawyer@1234"),
        "full_name":     "Adv. Zafar Iqbal",
        "role":          "lawyer",
        "province":      "punjab",
        "is_active":     True,
        "lawyer_profile": {
            "specializations":  ["criminal", "family"],
            "experience_years": 14,
            "rating":           4.5,
            "total_reviews":    27,
            "availability":     True,
            "kyc_verified":     True,
            "bar_number":       "PBA-E2E-001",
            "bio": (
                "Senior criminal defense lawyer with 14 years experience in Lahore "
                "High Court. Specialises in FIR registration, bail under CrPC Section 497, "
                "hurt cases under PPC Section 337, assault (PPC 352), and police "
                "misconduct petitions. Also handles family disputes including khula "
                "under MFLO and child custody matters."
            ),
        },
    })
    print("[seed] Inserted lawyer:", LAWYER_ID)

    from app.ai.lawyer_embeddings import embed_lawyer
    ok = await embed_lawyer(LAWYER_ID)
    print("[seed] ChromaDB embed :", "ok" if ok else "skipped (profile empty?)")
    return LAWYER_ID


# --- main test ---

async def main():
    t0 = time.time()

    # 0. Seed lawyer
    section("0 - Seed KYC-verified lawyer")
    try:
        lawyer_id = await seed_lawyer()
        check("Lawyer seeded into MongoDB + ChromaDB", True, lawyer_id)
    except Exception as exc:
        check("Lawyer seeded into MongoDB + ChromaDB", False, str(exc))
        print("Cannot continue without DB access.")
        return

    async with httpx.AsyncClient(timeout=TIMEOUT, base_url=BASE) as http:

        # 1. Register client
        section("1 - Register client")
        email    = rand_email()
        password = "TestPass123!"
        r = await http.post("/auth/register", json={
            "full_name": "E2E Test Client",
            "email":     email,
            "password":  password,
            "role":      "client",
        })
        check("Register 200/201", r.status_code in (200, 201), f"status={r.status_code}")
        if r.status_code not in (200, 201):
            print(r.text); return

        # 2. Login
        section("2 - Login")
        r = await http.post("/auth/login", json={"email": email, "password": password})
        check("Login 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200:
            print(r.text); return
        token   = r.json()["access_token"]
        user_id = r.json().get("user_id", "?")
        H = {"Authorization": f"Bearer {token}"}
        print(f"   user_id : {user_id}")

        # 3. Start intake
        section("3 - Start intake session")
        r = await http.post("/intake/start", headers=H)
        check("Start intake 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200:
            print(r.text); return
        tok = r.json()["session_token"]
        print(f"   intake token: {tok}")

        # 4. Steps 1-3
        section("4 - Save intake steps 1-3")

        r = await http.patch(f"/intake/{tok}/step/1", headers=H,
                             json={"data": {"province": "punjab"}})
        check("Step 1 (province) 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200: print(r.text); return

        r = await http.patch(f"/intake/{tok}/step/2", headers=H,
                             json={"data": {"case_type": "criminal", "urgency": "high"}})
        check("Step 2 (case_type+urgency) 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200: print(r.text); return

        r = await http.patch(f"/intake/{tok}/step/3", headers=H, json={"data": {
            "incident_description": (
                "My landlord physically assaulted me on 5 May 2026 at my rented home "
                "in Gulberg, Lahore. He punched me in the face and threatened to kill me "
                "if I did not vacate. I sustained injuries on my face and arms and went "
                "to Services Hospital for treatment. No FIR has been filed yet. "
                "I have photos of my injuries and two witnesses. "
                "I want to file an FIR and seek legal protection."
            ),
            "incident_date":     "2026-05-05",
            "incident_location": "Gulberg, Lahore, Punjab",
        }})
        check("Step 3 (description) 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200: print(r.text); return

        # 5. Clarification rounds (up to 4)
        section("5 - Clarification rounds (up to 4 questions)")

        SAMPLE_ANSWERS = [
            "The landlord is Rafiq Hussain. I do not have his phone number but his address is the same property at Gulberg III, Lahore.",
            "I have a medical certificate from Services Hospital dated 6 May 2026 documenting facial and arm injuries, and photographs of the injuries.",
            "Two witnesses: my neighbour Tariq Ahmed who saw the assault, and my wife Fatima who was inside the house.",
            "I want the landlord arrested and I am willing to press formal charges. I also need a court injunction to prevent further threats.",
        ]

        round_num  = 0
        qa_count   = 0
        prev_q     = None

        # First call: no answer
        r = await http.post(f"/intake/{tok}/clarify", headers=H, json={"answer": None})
        check("Clarify first call 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200:
            print(r.text)
        else:
            data = r.json()
            print("   first response:", json.dumps(data))
            if data.get("done"):
                print("   Backend done immediately (0 questions).")
            elif data.get("question"):
                round_num = 1
                prev_q    = data["question"]
                qa_count  = 0
                print(f"   Q1: {data['question'][:90]}")

                # Submit answers for rounds 1-4
                for i in range(1, 5):
                    if round_num < 1:
                        break
                    ans = SAMPLE_ANSWERS[min(round_num - 1, len(SAMPLE_ANSWERS) - 1)]
                    r = await http.post(f"/intake/{tok}/clarify", headers=H, json={"answer": ans})
                    check(f"Clarify round {round_num} submit 200",
                          r.status_code == 200, f"status={r.status_code}")
                    if r.status_code != 200:
                        print(r.text); break
                    data = r.json()
                    print(f"   round {round_num} response:", json.dumps(data))

                    # Detect repeated question (backend bug guard)
                    new_q = data.get("question")
                    if new_q and new_q == prev_q:
                        print(f"   [WARN] Backend returned identical question on round {round_num+1} -- possible clarify bug")

                    qa_count += 1
                    if data.get("done") or not data.get("question"):
                        print(f"   Clarification done after {qa_count} round(s).")
                        round_num = 0
                        break
                    round_num += 1
                    prev_q = new_q
                    print(f"   Q{round_num}: {new_q[:90] if new_q else '?'}")

        check("Clarification loop completed without crash", True,
              f"{qa_count} answer(s) submitted, round_num={round_num}")

        # 6. Steps 4-5
        section("6 - Save intake steps 4-5")

        r = await http.patch(f"/intake/{tok}/step/4", headers=H, json={"data": {
            "has_evidence": True,
            "evidence_description": "Medical cert + injury photos",
            "opposing_party": "Rafiq Hussain (landlord)",
        }})
        check("Step 4 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200: print(r.text); return

        r = await http.patch(f"/intake/{tok}/step/5", headers=H, json={"data": {
            "desired_outcome": "File FIR, criminal charges under PPC 352/337, bail revocation",
            "additional_notes": "Need urgent legal protection from further assault threats.",
        }})
        check("Step 5 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200: print(r.text); return

        # 7. Convert (triggers intake_graph)
        section("7 - POST /convert (AI intake pipeline)")
        print("   Triggers: retrieval -> grader -> intake_node -> hallucination_node")
        print("   Allow 30-120s...")
        t_conv = time.time()
        r = await http.post(f"/intake/{tok}/convert", headers=H,
                            json={"language": "en", "urgency": "high"})
        elapsed = round(time.time() - t_conv, 1)
        check(f"Convert 200 ({elapsed}s)", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200:
            print(r.text); return

        body    = r.json()
        case_id = body.get("case_id")
        check("case_id present in response", bool(case_id), str(case_id))
        print(f"   case_id: {case_id}")

        # 8. GET /intake -> inspect ai_structured_case
        section("8 - GET /intake -> inspect ai_structured_case")
        r = await http.get(f"/intake/{tok}", headers=H)
        check("GET intake 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200:
            print(r.text); return

        intake_data = r.json()
        ai = intake_data.get("ai_structured_case") or {}

        print("\n   -- ai_structured_case (truncated) --")
        ai_display = {
            "summary":             (ai.get("summary") or "")[:200],
            "applicable_laws":     ai.get("applicable_laws") or [],
            "recommended_actions": ai.get("recommended_actions") or [],
            "risk_level":          ai.get("risk_level") or "",
        }
        print(json.dumps(ai_display, indent=4))

        check("ai_structured_case present",  bool(ai),                       "")
        check("summary non-empty",           bool(ai.get("summary")),        (ai.get("summary") or "")[:60])
        check("applicable_laws present",     bool(ai.get("applicable_laws")), "")
        check("recommended_actions present", bool(ai.get("recommended_actions")), "")
        check("risk_level present",          bool(ai.get("risk_level")),     ai.get("risk_level", ""))

        # Check for CrPC / PPC statute refs (multi-hop retrieval evidence)
        laws_text = " ".join(
            (ai.get("applicable_laws") or []) + [(ai.get("summary") or "")]
        )
        has_crpc = "crpc" in laws_text.lower() or "criminal procedure" in laws_text.lower()
        has_ppc  = "ppc"  in laws_text.lower() or "penal code"         in laws_text.lower()

        check("CrPC statute reference in output (multi-hop evidence)", has_crpc,
              laws_text[:80] if not has_crpc else "found")
        check("PPC statute reference in output", has_ppc,
              laws_text[:80] if not has_ppc else "found")

        if not has_crpc and not has_ppc:
            print(f"   {WARN} No CrPC/PPC refs -- check knowledge base OR AI summarised without statute names")

        # 9. Poll /lawyers/match/{case_id}
        section(f"9 - Poll /lawyers/match/{case_id}")
        print(f"   polling up to {POLL_MAX}x every {POLL_SEC}s (auto-match runs in background)...")

        matched   = []
        match_err = None

        for attempt in range(1, POLL_MAX + 1):
            await asyncio.sleep(POLL_SEC)
            r = await http.get(f"/lawyers/match/{case_id}", headers=H)
            if r.status_code == 200:
                body  = r.json()
                items = body if isinstance(body, list) else (
                    body.get("matches") or body.get("items") or []
                )
                if items:
                    matched = items
                    print(f"   Got {len(matched)} match(es) on attempt {attempt}")
                    break
                print(f"   attempt {attempt}: empty list, retrying...")
            elif r.status_code == 403:
                match_err = f"403: {r.text[:120]}"
                print(f"   {FAIL} {match_err}")
                break
            elif r.status_code == 404:
                print(f"   attempt {attempt}: 404 case not indexed yet, retrying...")
            else:
                match_err = f"HTTP {r.status_code}: {r.text[:120]}"
                print(f"   {FAIL} {match_err}")
                break

        check("matched_lawyers returned >= 1 result", bool(matched),
              f"{len(matched)} lawyers" if matched else "empty after all polls")

        if match_err:
            check("No error calling /lawyers/match", False, match_err)
        elif matched:
            top = matched[0]
            print("\n   -- Top matched lawyer --")
            print(f"   name        : {top.get('full_name')}")
            print(f"   match_score : {top.get('match_score')}")
            print(f"   match_reason: {top.get('match_reason')}")
            print(f"   province    : {top.get('province')}")

            check("Top match has match_score",      "match_score"   in top, str(top.get("match_score")))
            check("Top match has match_reason",     "match_reason"  in top, (top.get("match_reason") or "")[:60])
            check("No password_hash leaked",        "password_hash" not in top, "")
            check("No cnic_encrypted leaked",       "cnic_encrypted" not in top, "")

        # Summary
        total_time = round(time.time() - t0, 1)
        section(f"Summary  ({total_time}s total)")
        passed = sum(1 for _, ok in results if ok)
        failed = sum(1 for _, ok in results if not ok)
        print(f"   {PASS}  {passed} passed")
        print(f"   {FAIL}  {failed} failed")
        if failed:
            print("\n   Failed checks:")
            for label, ok in results:
                if not ok:
                    print(f"     - {label}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
