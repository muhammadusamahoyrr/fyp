# Manual smoke scripts

These five files were at `backend/` root named `test_*.py`. They are **not pytest
tests** — none contains a single `def test_*` function, and several run code at
import time (`smoke_pipeline_nodes.py` calls `connect_chroma()` on the first
line). They are manual scripts that drive a **live server on `:8000`**.

They were never collected, because `pytest.ini` sets `testpaths = tests`. That
was the correct outcome for the wrong reason: had they been collected, pytest
would have imported five modules with zero tests and executed their side effects.

Renamed out of the `test_` namespace so they stop reading as coverage that
exists. Nothing imports them; moving them changes no behaviour.

## Running one

Start the backend first:

```
backend/venv/Scripts/uvicorn.exe app.main:app --port 8000
```

Then, from `backend/`:

| Script | What it drives |
|---|---|
| `smoke_full_e2e.py` | Seeds a KYC-verified lawyer, registers a client, runs intake → case → matching |
| `smoke_intake_e2e.py` | Intake flow including clarification rounds |
| `smoke_lawyer_matching.py` | Admin embed-all, then `GET /lawyers/match/{case_id}` |
| `smoke_chat_ws.py` | WebSocket chat turn against a running server |
| `smoke_pipeline_nodes.py` | Retrieval → generation → hallucination nodes directly (no server) |

```
./venv/Scripts/python.exe scripts/manual_smoke/smoke_full_e2e.py
```

## If you want these in CI

They need converting to real pytest tests — `def test_*` functions using the
`mongo` fixture from `tests/conftest.py` and FastAPI's `TestClient` instead of a
live `:8000`. That is a rewrite, not a move, and is out of scope for the current
remediation batch.
