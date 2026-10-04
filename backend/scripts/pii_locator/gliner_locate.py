"""Run the development PII locator (gliner_multi-v2.1) FULLY OFFLINE over plain texts.

Run with the ISOLATED environment, never the backend venv:

    <ML>/venv-gliner/Scripts/python.exe backend/scripts/pii_locator/gliner_locate.py <ML> <in.json> <out.json> [variant]

[variant]: `as_loaded` (default) or `mistral_regex_fix` -- the tokenizer pre-tokenizer
replacement transformers applies under `fix_mistral_regex=True`, for the A/B run only.

<in.json>: [{"id", "text"}] -- plain document text only, never labels.
<out.json>: per document the entities found, with offsets into the ORIGINAL
text, plus timings, chunking and peak RAM.

Guarantees:
  * offline: HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE are set and every socket
    connection is refused before any library is imported;
  * the files loaded are the pinned ones: their SHA-256 must match the
    manifest written by download_gliner.py, or nothing runs;
  * no truncation: the text is cut into OVERLAPPING chunks with the model's
    own word splitter; every chunk is measured with the model's tokenizer,
    including the label prompt, and must fit; gliner's own truncation
    warning is an error; every word is covered by at least one chunk.
"""
from __future__ import annotations

import os
import socket
import sys
import warnings
from pathlib import Path

ML = Path(sys.argv[1]).resolve()
os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HOME": str(ML / "hf-home"),
                   "HF_HUB_CACHE": str(ML / "hf-cache"), "HF_HUB_DISABLE_TELEMETRY": "1"})


def _no_network(*_a, **_k):
    raise RuntimeError("network access is disabled for the offline locator")


socket.socket.connect = _no_network          # type: ignore[assignment]
socket.create_connection = _no_network       # type: ignore[assignment]

import hashlib  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402

import psutil  # noqa: E402
import torch  # noqa: E402

warnings.filterwarnings("error", message=r"Sentence of length .* has been truncated")
torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))

from gliner import GLiNER  # noqa: E402

LABELS = ["person", "address", "location", "organization"]
THRESHOLD = 0.2                 # report everything >= 0.2 with its score; the benchmark picks cut-offs
CHUNK_WORDS = 160
OVERLAP_WORDS = 40
LIMIT_SUBWORDS = 512            # mDeBERTa's position limit
PROMPT_MARGIN = 24


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verified_model_dir() -> Path:
    manifest = json.loads((ML / "gliner_multi-v2.1.manifest.json").read_text(encoding="utf-8"))
    model_dir = None
    for repo in manifest["repos"]:
        for f in repo["files"]:
            path = Path(f["local_path"])
            if sha256(path) != f["sha256"]:
                raise SystemExit(f"refused: {repo['repo']}/{f['name']} does not match its pinned sha256")
            if repo["repo"] == "urchade/gliner_multi-v2.1":
                model_dir = path.parent
    return model_dir


def chunks(words: list[tuple[str, int, int]]):
    """(first word, last word exclusive) windows that overlap and cover every word."""
    if not words:
        return
    i = 0
    while True:
        j = min(len(words), i + CHUNK_WORDS)
        yield i, j
        if j == len(words):
            return
        i = j - OVERLAP_WORDS


def main() -> int:
    in_path, out_path = Path(sys.argv[2]), Path(sys.argv[3])
    docs = json.loads(in_path.read_text(encoding="utf-8"))
    began = time.perf_counter()
    model_dir = verified_model_dir()
    model = GLiNER.from_pretrained(str(model_dir), local_files_only=True)
    model.eval()
    variant = sys.argv[4] if len(sys.argv) > 4 else "as_loaded"
    if variant == "mistral_regex_fix":
        # Exactly what transformers does for fix_mistral_regex=True (tokenization_utils_base.py).
        import tokenizers
        model.data_processor.transformer_tokenizer.backend_tokenizer.pre_tokenizer[0] = tokenizers.pre_tokenizers.Split(
            pattern=tokenizers.Regex(
                r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+|[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*|\p{N}| ?[^\s\p{L}\p{N}]+[\r\n/]*|\s*[\r\n]+|\s+(?!\S)|\s+"),
            behavior="isolated")
    elif variant != "as_loaded":
        raise SystemExit(f"unknown variant {variant!r}")
    load_s = time.perf_counter() - began
    splitter = model.data_processor.words_splitter
    tokenizer = model.data_processor.transformer_tokenizer
    prompt = sum(len(tokenizer.tokenize(f"<<ENT>> {label}")) for label in LABELS) + PROMPT_MARGIN

    out = {"model": "urchade/gliner_multi-v2.1", "revision": "443d26d654e0324125a96bebd8e796c14ff2efe6",
           "tokenizer_variant": variant,
           "labels": LABELS, "threshold_reported": THRESHOLD, "load_seconds": round(load_s, 2),
           "chunk_words": CHUNK_WORDS, "overlap_words": OVERLAP_WORDS, "documents": {}}
    proc = psutil.Process()
    for doc in docs:
        text = doc["text"]
        words = [(w, s, e) for w, s, e in splitter(text)]
        covered = [False] * len(words)
        found: dict[tuple[int, int, str], float] = {}
        t0 = time.perf_counter()
        n_chunks = 0
        for a, b in chunks(words):
            start, end = words[a][1], words[b - 1][2]
            piece = text[start:end]
            subwords = len(tokenizer([w for w, _, _ in words[a:b]], is_split_into_words=True)["input_ids"])
            if subwords + prompt > LIMIT_SUBWORDS:
                raise SystemExit(f"refused: {doc['id']} chunk {a}-{b} needs {subwords + prompt} subwords "
                                 f"(> {LIMIT_SUBWORDS}); nothing is truncated silently")
            for ent in model.predict_entities(piece, LABELS, threshold=THRESHOLD, flat_ner=False):
                key = (start + ent["start"], start + ent["end"], ent["label"])
                found[key] = max(found.get(key, 0.0), float(ent["score"]))
            for k in range(a, b):
                covered[k] = True
            n_chunks += 1
        if not all(covered):
            raise SystemExit(f"refused: {doc['id']} has words no chunk covered")
        ms = (time.perf_counter() - t0) * 1000
        ents = [{"start": s, "end": e, "label": lab, "score": round(sc, 4)} for (s, e, lab), sc in sorted(found.items())]
        for ent in ents:
            assert text[ent["start"]:ent["end"]].strip(), "empty entity span"
        out["documents"][doc["id"]] = {"entities": ents, "ms": round(ms, 1), "chunks": n_chunks,
                                       "words": len(words), "chars": len(text)}
    mem = proc.memory_info()
    out["peak_rss_mb"] = round(getattr(mem, "peak_wset", mem.rss) / 1e6, 1)
    out["total_seconds"] = round(time.perf_counter() - began, 2)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"documents={len(docs)} load={load_s:.1f}s total={out['total_seconds']}s peak_rss={out['peak_rss_mb']}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
