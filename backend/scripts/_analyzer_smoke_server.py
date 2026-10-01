"""Run the REAL app for the analyzer smoke test, isolated from shared state.

Started by scripts/analyzer_smoke.py with environment overrides (smoke
database, no Redis, no AI/SMTP/telemetry/payment credentials). Two things
cannot be switched off by settings and are patched here, before the app
starts:

  * Chroma is EMBEDDED at backend/chroma_data. A second process opening it
    while the dev server runs can corrupt it, so this process gets an empty
    temporary directory instead.
  * The background model warmup (Whisper, embeddings) is skipped: heavy, and
    irrelevant to the analyzer.

Usage (normally via analyzer_smoke.py):  python scripts/_analyzer_smoke_server.py <port>
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.db import chroma  # noqa: E402

chroma._CHROMA_PATH = pathlib.Path(tempfile.mkdtemp(prefix="analyzer-smoke-chroma-"))

import app.main as main  # noqa: E402


async def _no_warmup():
    return None


main._warmup_models = _no_warmup

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
