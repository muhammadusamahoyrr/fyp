#!/usr/bin/env python3
"""Back up attorney_ai and the artifacts its documents reference. READ-ONLY.

`mongodump` is not installed here, so this writes the same layout mongodump
produces -- `<collection>.bson` holding concatenated BSON documents, beside a
`<collection>.metadata.json` carrying the index definitions. If the database
tools are installed later, `mongorestore` reads this directly; nothing about the
format is bespoke.

SCOPE: the whole database, not just the collections the migration is believed to
touch. A backup scoped by someone's reading of apply() fails precisely when that
reading is wrong, and at 76 MiB the saving would buy nothing.

VERIFICATION is the point. Writing files is easy; the question is whether they
hold what the database holds. Every collection is read back off disk, decoded,
and compared to the live source by canonical content fingerprint -- the same
function the capture contract uses -- not merely counted.

Reads only. No write API is called against Mongo, and nothing outside the
backup directory is created or modified.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import bson  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from app.db.v2_capture_contract import canonical_document_bytes  # noqa: E402


def fingerprint(documents) -> str:
    """Order-independent content hash. Same construction as the capture
    contract's canonical_fingerprint, so a match means byte-identical content
    rather than merely the same number of rows."""
    digests = sorted(hashlib.sha256(canonical_document_bytes(d)).digest()
                     for d in documents)
    combined = hashlib.sha256()
    for digest in digests:
        combined.update(digest)
    return combined.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    uri = Path(os.environ["TEMP"], "v2s.txt").read_text(encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path.home() / f"v2-backup-{stamp}"
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out.name}")
    (out / "mongo").mkdir(parents=True)
    (out / "artifacts").mkdir()

    client = MongoClient(uri, serverSelectionTimeoutMS=30000)
    db = client["attorney_ai"]

    manifest = {
        "tool": "v2_backup",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": "attorney_ai",
        "format": "mongodump-compatible: <collection>.bson + .metadata.json",
        "scope": "entire database plus every artifact referenced by a document",
        "collections": {},
        "artifacts": {},
    }

    print("=== dumping collections ===")
    live = {}
    for name in sorted(db.list_collection_names()):
        docs = list(db[name].find({}))
        live[name] = docs
        payload = b"".join(bson.encode(d) for d in docs)
        (out / "mongo" / f"{name}.bson").write_bytes(payload)
        indexes = list(db[name].list_indexes())
        (out / "mongo" / f"{name}.metadata.json").write_text(
            json.dumps({"collectionName": name, "options": {},
                        "indexes": json.loads(bson.json_util.dumps(indexes))},
                       indent=2), encoding="utf-8")
        manifest["collections"][name] = {
            "documents": len(docs),
            "bson_bytes": len(payload),
            "content_fingerprint": fingerprint(docs),
            "indexes": len(indexes),
        }
        print(f"  {name:32} {len(docs):>6} docs  {len(payload):>12,} bytes")

    print()
    print("=== copying referenced artifacts ===")
    referenced, missing = {}, []
    for doc in live.get("documents", []):
        path = doc.get("file_path")
        if not path:
            continue
        source = Path(path)
        if not source.is_file():
            missing.append(doc["_id"])
            continue
        target = out / "artifacts" / source.name
        target.write_bytes(source.read_bytes())
        referenced[str(doc["_id"])] = {"filename": source.name,
                                       "sha256": sha256_file(source),
                                       "size": source.stat().st_size}
    manifest["artifacts"] = referenced
    manifest["artifacts_referenced"] = len(referenced)
    manifest["artifacts_missing"] = missing
    print(f"  copied {len(referenced)} referenced artifact(s); "
          f"{len(missing)} referenced but missing")

    print()
    print("=== verification: read back off disk and compare to source ===")
    problems = []
    for name, recorded in manifest["collections"].items():
        raw = (out / "mongo" / f"{name}.bson").read_bytes()
        decoded = bson.decode_all(raw)
        if len(decoded) != recorded["documents"]:
            problems.append(f"{name}: {len(decoded)} decoded vs "
                            f"{recorded['documents']} dumped")
            continue
        if fingerprint(decoded) != recorded["content_fingerprint"]:
            problems.append(f"{name}: content fingerprint differs after reload")
            continue
        if fingerprint(decoded) != fingerprint(live[name]):
            problems.append(f"{name}: content differs from the live source")
    print(f"  collections verified : "
          f"{len(manifest['collections']) - len(problems)}"
          f"/{len(manifest['collections'])}")

    artifact_problems = []
    for doc_id, info in referenced.items():
        copied = out / "artifacts" / info["filename"]
        if not copied.is_file():
            artifact_problems.append(f"{info['filename']}: not in the backup")
        elif sha256_file(copied) != info["sha256"]:
            artifact_problems.append(f"{info['filename']}: sha256 differs")
    print(f"  artifacts verified   : "
          f"{len(referenced) - len(artifact_problems)}/{len(referenced)}")

    manifest["verification"] = {
        "collection_problems": problems,
        "artifact_problems": artifact_problems,
        "usable": not problems and not artifact_problems and not missing,
        "method": ("every .bson decoded off disk and compared to the live "
                   "source by canonical content fingerprint; every artifact "
                   "re-hashed after copying"),
        "limitation": ("not a restore rehearsal. mongorestore is not installed, "
                       "so this proves the files hold the database's content, "
                       "not that a restore tool consumed them."),
    }

    payload = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    (out / "BACKUP-MANIFEST.json").write_bytes(payload)
    (out / "BACKUP-MANIFEST.json.sha256").write_bytes(
        f"{hashlib.sha256(payload).hexdigest()}  BACKUP-MANIFEST.json\n".encode())

    try:
        from capture_v2_snapshot_manifest import protect  # type: ignore
    except Exception:
        sys.path.insert(0, str(BACKEND / "scripts"))
        from capture_v2_snapshot_manifest import protect  # type: ignore
    ok, detail = protect(out, is_dir=True)
    manifest_protection = detail if ok else f"NOT PROTECTED: {detail}"

    client.close()

    print()
    print(f"location   {out}")
    print(f"protection {manifest_protection}")
    print(f"documents  {sum(c['documents'] for c in manifest['collections'].values())}")
    print(f"artifacts  {len(referenced)} referenced, {len(missing)} missing")
    print(f"USABLE     {manifest['verification']['usable']}")
    if problems or artifact_problems:
        for p in problems + artifact_problems:
            print(f"  PROBLEM: {p}")
    return 0 if manifest["verification"]["usable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
