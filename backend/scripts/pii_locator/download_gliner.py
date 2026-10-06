"""Download the development PII locator at its PINNED revision (ANALYZER_PII_MODEL_SHORTLIST.md).

Run with the ISOLATED environment, never the backend venv:

    <ML>/venv-gliner/Scripts/python.exe backend/scripts/pii_locator/download_gliner.py <ML>

<ML> is outside the Git repository (the model cache never enters Git). Only
the files actually needed are fetched, each at the pinned commit, and each
LFS file is verified against the SHA-256 the Hub publishes for it. A manifest
of every file's SHA-256 is written next to the cache and copied into the repo
(hashes only). Development use only: this does NOT select the model.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ML = Path(sys.argv[1]).resolve()
CACHE = ML / "hf-cache"
os.environ["HF_HOME"] = str(ML / "hf-home")
os.environ.pop("HF_HUB_OFFLINE", None)

from huggingface_hub import HfApi, hf_hub_download  # noqa: E402

PINNED = [
    ("urchade/gliner_multi-v2.1", "443d26d654e0324125a96bebd8e796c14ff2efe6",
     ["gliner_config.json", "model.safetensors", "README.md"]),
    ("microsoft/mdeberta-v3-base", "a0484667b22365f84929a935b5e50a51f71f159d",
     ["config.json", "spm.model", "tokenizer_config.json"]),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    api = HfApi()
    manifest = {"purpose": "development PII-locator benchmark only; not selected for production", "repos": []}
    for repo, revision, files in PINNED:
        info = api.model_info(repo, revision=revision, files_metadata=True)
        if info.sha != revision:
            print(f"refused: {repo} resolved to {info.sha}, not the pinned {revision}", file=sys.stderr)
            return 2
        published = {s.rfilename: s for s in info.siblings}
        entry = {"repo": repo, "revision": revision, "files": []}
        for name in files:
            local = Path(hf_hub_download(repo, name, revision=revision, cache_dir=str(CACHE)))
            digest = sha256(local)
            lfs = getattr(published[name], "lfs", None)
            expected = (lfs.sha256 if hasattr(lfs, "sha256") else (lfs or {}).get("sha256")) if lfs else None
            if expected and expected != digest:
                print(f"refused: {repo}/{name} sha256 {digest} != published {expected}", file=sys.stderr)
                return 2
            entry["files"].append({"name": name, "sha256": digest, "size": local.stat().st_size,
                                   "verified_against_hub_lfs_sha256": bool(expected),
                                   "local_path": str(local)})
            print(f"{repo}@{revision[:8]} {name} {local.stat().st_size / 1e6:.1f} MB sha256 {digest[:16]}"
                  f"{' (verified)' if expected else ' (recorded)'}")
        # Offline loading resolves the encoder by name ("main"): point main at the pinned commit.
        refs = CACHE / f"models--{repo.replace('/', '--')}" / "refs"
        refs.mkdir(parents=True, exist_ok=True)
        (refs / "main").write_text(revision, encoding="utf-8")
        manifest["repos"].append(entry)
    (ML / "gliner_multi-v2.1.manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("manifest:", ML / "gliner_multi-v2.1.manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
