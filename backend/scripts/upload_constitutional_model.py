"""upload_constitutional_model.py — publish the constitutional-only weights.

Why this exists
---------------
usama1111/e5-pakistani-legal was overwritten on 2026-08-07 15:12 UTC. The
constitutional-only weights survive only at revision 445e441d and in the local
backup taken before the overwrite. Both models are needed for the paper's
three-way ablation, so the constitutional one gets its own repo where nothing
else will land on top of it.

The weights hash is verified BEFORE upload. Publishing the wrong model under a
name the paper will cite is the failure this whole episode was about, and a
hash check is the cheapest possible guard against repeating it.

Authentication
--------------
No token is read from, or written to, this file. Log in first, in your own
terminal:

    backend\\venv\\Scripts\\huggingface-cli.exe login

Then run this script.

Usage
-----
  python scripts/upload_constitutional_model.py --dry-run
  python scripts/upload_constitutional_model.py --repo usama1111/e5-pak-legal-constitutional
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

LOCAL = Path("models/backup/e5-constitutional-445e441d")
# Full SHA-256 (64 hex chars). An earlier version stored the 40-char
# truncated display value and rejected the correct file — the guard failed
# safe, but a wrong constant is still a wrong constant.
EXPECTED_SHA = "9761c235d497c6c314037f961c5234414ab6cbeeee7160af6952965ac31ea3b4"
DEFAULT_REPO = "usama1111/e5-pak-legal-constitutional"

CARD = """---
license: mit
base_model: intfloat/multilingual-e5-base
library_name: sentence-transformers
pipeline_tag: sentence-similarity
tags:
  - legal
  - pakistan
  - retrieval
  - constitutional-law
language:
  - en
  - ur
---

# e5-pak-legal-constitutional

`intfloat/multilingual-e5-base` fine-tuned for retrieval over the **Constitution
of Pakistan 1973**.

This is the CONSTITUTIONAL-ONLY model. A separate, more broadly trained model
covers criminal, evidence, civil procedure and family law as well; this one is
published so the two can be compared.

## Training

- 471 question/article pairs derived from [LEGAL-UQA](https://arxiv.org/abs/2410.13013)
- MultipleNegativesRankingLoss, hard negatives mined from the deployed retriever
- 2 epochs, batch 32, lr 2e-5, max_seq_length 224
- Train/test split by connected components over shared gold chunks, so no gold
  chunk appears in both halves

## Measured results

Held-out LEGAL-UQA questions, gold resolved against the authenticated National
Assembly text:

| configuration | Hit@1 base | Hit@1 tuned | delta |
|---|---|---|---|
| dense only | 0.4380 | 0.6033 | **+16.5** |
| hybrid (BM25 0.6 / dense 0.4) | 0.5207 | 0.5868 | **+6.6** |

The hybrid figure is the one that matters for a deployed system: BM25 already
supplies much of what fine-tuning teaches the dense channel, so a single-channel
gain does not transfer proportionally to a fused retriever.

## Limitations

- **Constitutional law only.** On citation-style questions from other domains it
  gives roughly +5 Hit@1, against +16.5 on LEGAL-UQA-style constitutional
  questions — the gain is bound to both the domain and the question style.
- Weaker on exact-citation lookups than the base model. Fine-tuning shifted it
  toward semantic matching; BM25 compensates in a hybrid setup.
- Evaluated on 121 held-out questions. Small, and generated rather than
  practitioner-authored.

## Usage

```python
from sentence_transformers import SentenceTransformer

m = SentenceTransformer("{repo}")
q = m.encode(["query: What are the fundamental rights?"], normalize_embeddings=True)
p = m.encode(["passage: 25. All citizens are equal before law..."], normalize_embeddings=True)
```

The `query:` / `passage:` prefixes are required — the model was trained with them.
"""


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def main(a) -> int:
    from huggingface_hub import HfApi, get_token

    if not LOCAL.exists():
        raise SystemExit(f"{LOCAL} not found — nothing to upload")

    weights = LOCAL / "model.safetensors"
    print(f"\n  verifying {weights} …")
    sha = _sha256(weights)
    print(f"  sha256   : {sha[:40]}")
    print(f"  expected : {EXPECTED_SHA[:40]}")
    if sha != EXPECTED_SHA:
        raise SystemExit(
            "WEIGHTS MISMATCH — this is not the constitutional model. Refusing "
            "to publish: uploading the wrong weights under a name the paper "
            "cites is exactly the failure this repo exists to prevent."
        )
    print("  weights confirmed: constitutional-only model")

    files = sorted(p.name for p in LOCAL.iterdir() if p.is_file())
    print(f"\n  files to upload ({len(files)}):")
    for f in files:
        print(f"    {f}")

    if a.dry_run:
        print("\n  dry run — nothing uploaded.\n")
        return 0

    if not get_token():
        raise SystemExit(
            "not logged in. Run this in your own terminal first, so no token "
            "ends up in a transcript:\n"
            "    backend\\venv\\Scripts\\huggingface-cli.exe login"
        )

    api = HfApi()
    print(f"\n  logged in as: {api.whoami().get('name')}")
    api.create_repo(a.repo, repo_type="model", exist_ok=True, private=False)

    (LOCAL / "README.md").write_text(CARD.replace("{repo}", a.repo), encoding="utf-8")
    api.upload_folder(folder_path=str(LOCAL), repo_id=a.repo, repo_type="model",
                      commit_message="constitutional-only e5, revision 445e441d")

    info = api.model_info(a.repo, files_metadata=True)
    remote = {s.rfilename: s for s in info.siblings}.get("model.safetensors")
    r_sha = getattr(getattr(remote, "lfs", None), "sha256", None)
    print(f"\n  uploaded -> https://huggingface.co/{a.repo}")
    print(f"  remote sha256: {(r_sha or '?')[:40]}")
    print(f"  ROUND-TRIP VERIFIED: {r_sha == sha}")
    if r_sha != sha:
        print("  WARNING: remote hash differs — do not cite this repo until resolved")
        return 1
    print()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Publish the constitutional-only model.")
    p.add_argument("--repo", default=DEFAULT_REPO)
    p.add_argument("--dry-run", action="store_true")
    raise SystemExit(main(p.parse_args()))
