"""WebSocket chat test — run after server restart."""
import asyncio
import json
import random
import secrets
import string

import httpx
import websockets

BASE    = "http://127.0.0.1:8000/api/v1"
WS_BASE = "ws://127.0.0.1:8000"

def rand_email():
    s = "".join(random.choices(string.ascii_lowercase, k=6))
    return f"ws_{s}@example.com"

async def main():
    async with httpx.AsyncClient(timeout=30) as http:
        # Register + login
        # Random per run: a constant here is a committed credential in a
        # public repository, and this account is created by registering.
        email, pw = rand_email(), "Aa1" + secrets.token_urlsafe(24)
        r = await http.post(f"{BASE}/auth/register", json={"full_name": "WS Tester", "email": email, "password": pw, "role": "client"})
        print(f"Register: {r.status_code}")

        r = await http.post(f"{BASE}/auth/login", json={"email": email, "password": pw})
        print(f"Login: {r.status_code}")
        if r.status_code != 200:
            print(r.text); return
        access_token = r.json()["access_token"]

    session_id = "test-" + "".join(random.choices(string.ascii_lowercase, k=8))
    uri = f"{WS_BASE}/ws/chat/{session_id}?token={access_token}"

    print(f"\nConnecting to {uri[:60]}...")
    async with websockets.connect(uri) as ws:
        queries = [
            {
                "content":   "My landlord beat me up. What can I do under Pakistani law?",
                "case_type": "criminal",
                "province":  "punjab",
                "language":  "en",
            },
            {
                "content": "What is Section 506 of PPC?",
            },
        ]

        for q in queries:
            print(f"\n>> Sending: {q['content'][:60]}")
            await ws.send(json.dumps(q))

            # Collect messages until we get a final/clarification/error type
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
                msg = json.loads(raw)
                mtype = msg.get("type")
                print(f"<< [{mtype}]", end=" ")

                if mtype == "thinking":
                    print("(AI is thinking...)")
                elif mtype == "clarification":
                    print(f"Clarification: {msg.get('question', '')}")
                    break
                elif mtype == "final":
                    content = msg.get("content", "")
                    citations = msg.get("citations", [])
                    confidence = msg.get("confidence", 0)
                    print(f"confidence={confidence:.2f}, citations={len(citations)}")
                    print(content[:400])
                    break
                elif mtype == "error":
                    print(f"ERROR: {msg.get('content', '')}")
                    break
                else:
                    print(msg)
                    break

asyncio.run(main())
