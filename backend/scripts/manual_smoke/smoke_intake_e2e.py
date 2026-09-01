"""End-to-end intake flow test."""
import asyncio
import httpx
import json
import random
import secrets
import string

BASE = "http://127.0.0.1:8000/api/v1"

def rand_email():
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    return f"test_{suffix}@example.com"

async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        email = rand_email()
        # Random per run: a constant here is a committed credential in a
        # public repository, and this account is created by registering.
        password = "Aa1" + secrets.token_urlsafe(24)

        # 1. Register
        r = await client.post(f"{BASE}/auth/register", json={
            "full_name": "Test Client",
            "email": email,
            "password": password,
            "role": "client",
        })
        print(f"Register: {r.status_code}")
        if r.status_code not in (200, 201):
            print(r.text); return

        # 2. Login
        r = await client.post(f"{BASE}/auth/login", json={
            "email": email,
            "password": password,
        })
        print(f"Login: {r.status_code}")
        if r.status_code != 200:
            print(r.text); return
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Start intake
        r = await client.post(f"{BASE}/intake/start", headers=headers)
        print(f"Start intake: {r.status_code}")
        if r.status_code != 200:
            print(r.text); return
        intake_token = r.json()["session_token"]
        print(f"Intake token: {intake_token}")

        # 4. Step 1 — province (required)
        r = await client.patch(f"{BASE}/intake/{intake_token}/step/1", headers=headers, json={
            "data": {"province": "punjab", "full_name": "Test Client"}
        })
        print(f"Step 1: {r.status_code}")
        if r.status_code != 200: print(r.text); return

        # 5. Step 2 — case type + urgency (required)
        r = await client.patch(f"{BASE}/intake/{intake_token}/step/2", headers=headers, json={
            "data": {"case_type": "criminal", "urgency": "high"}
        })
        print(f"Step 2: {r.status_code}")
        if r.status_code != 200: print(r.text); return

        # 6. Step 3 — incident description (required)
        r = await client.patch(f"{BASE}/intake/{intake_token}/step/3", headers=headers, json={
            "data": {
                "incident_description": "My landlord physically assaulted me yesterday. He hit me with his fist and threatened to kill me if I did not leave the property. I have injuries on my face and arms.",
                "incident_date": "2026-05-05",
                "incident_location": "Lahore, Punjab",
            }
        })
        print(f"Step 3: {r.status_code}")
        if r.status_code != 200: print(r.text); return

        # 7. Step 4 — evidence (no required fields)
        r = await client.patch(f"{BASE}/intake/{intake_token}/step/4", headers=headers, json={
            "data": {
                "has_evidence": True,
                "evidence_description": "Medical certificate documenting injuries",
                "opposing_party": "Ahmed Khan",
            }
        })
        print(f"Step 4: {r.status_code}")
        if r.status_code != 200: print(r.text); return

        # 8. Step 5 — desired outcome (required)
        r = await client.patch(f"{BASE}/intake/{intake_token}/step/5", headers=headers, json={
            "data": {
                "desired_outcome": "File an FIR and pursue criminal charges against the landlord.",
                "additional_notes": "I want to file an FIR immediately.",
            }
        })
        print(f"Step 5: {r.status_code}")
        if r.status_code != 200: print(r.text); return

        # 9. Convert — triggers intake_graph
        print("\nCalling /convert (AI intake pipeline — allow 30-90s for first run)...")
        r = await client.post(
            f"{BASE}/intake/{intake_token}/convert",
            headers=headers,
            timeout=180.0,
        )
        print(f"Convert: {r.status_code}")
        if r.status_code != 200:
            print(r.text); return

        body = r.json()
        case_id = body.get("case_id")
        print(f"case_id: {case_id}")

        # 10. Fetch full intake to see ai_structured_case
        r = await client.get(f"{BASE}/intake/{intake_token}", headers=headers)
        print(f"GET intake: {r.status_code}")
        if r.status_code != 200:
            print(r.text); return

        intake_data = r.json()
        ai_data = intake_data.get("ai_structured_case")
        print("\n--- ai_structured_case ---")
        print(json.dumps(ai_data, indent=2, ensure_ascii=False))

asyncio.run(main())
