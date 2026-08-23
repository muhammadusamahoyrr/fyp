"""fetch_tuned_model.py — pull the fine-tuned retriever and make it loadable here.

The problem
-----------
The model was trained on Colab, which runs sentence-transformers 5.x. That
version records module paths in modules.json under a namespace that does not
exist in the 3.0.1 installed here:

    sentence_transformers.base.modules.transformer.Transformer
    sentence_transformers.sentence_transformer.modules.pooling.Pooling
    sentence_transformers.sentence_transformer.modules.normalize.Normalize

Loading it raises ModuleNotFoundError: No module named 'sentence_transformers.base'.

Upgrading sentence-transformers locally would change the library the LIVE
retriever encodes with, on a system whose production index was built by the
current version. Rewriting a three-line manifest is the smaller change, and it
touches nothing at inference time.

The weights, tokenizer and pooling configuration are untouched — only the class
paths in modules.json are translated to their 3.x equivalents.

Usage
-----
  python scripts/fetch_tuned_model.py
  python scripts/fetch_tuned_model.py --repo usama1111/e5-pakistani-legal
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_REPO = "usama1111/e5-pakistani-legal"
DEFAULT_DEST = Path("models/e5-pakistani-legal")

# The sequence length the model was trained and evaluated at in Colab. The
# uploaded config omits it; defaulting to the model's 512 would embed the corpus
# differently from the run that produced the +16.5 Hit@1 measurement.
TRAIN_MAX_SEQ = 224

# v5 path -> v3 path. Mapped by suffix so a future minor rename still matches.
_TRANSLATE = {
    "transformer.Transformer": "sentence_transformers.models.Transformer",
    "pooling.Pooling":         "sentence_transformers.models.Pooling",
    "normalize.Normalize":     "sentence_transformers.models.Normalize",
    "dense.Dense":             "sentence_transformers.models.Dense",
}


def _translate(module_type: str) -> str:
    for suffix, replacement in _TRANSLATE.items():
        if module_type.endswith(suffix):
            return replacement
    return module_type


def main(repo: str, dest: Path) -> int:
    from huggingface_hub import snapshot_download

    print(f"\n  downloading {repo} …")
    local = snapshot_download(repo_id=repo, local_dir=str(dest))
    local_path = Path(local)

    manifest = local_path / "modules.json"
    modules = json.loads(manifest.read_text(encoding="utf-8"))

    changed = []
    for m in modules:
        new = _translate(m["type"])
        if new != m["type"]:
            changed.append((m["type"], new))
            m["type"] = new
        # A module declaring a path must have that directory. Normalize carries
        # no state, and v5 records it without writing the folder — which older
        # loaders then fail to find.
        p = (m.get("path") or "").strip()
        if p and not (local_path / p).exists():
            (local_path / p).mkdir(parents=True, exist_ok=True)
            print(f"    created missing module dir: {p}")

    if changed:
        manifest.write_text(json.dumps(modules, indent=1), encoding="utf-8")
        print("\n  rewrote modules.json:")
        for old, new in changed:
            print(f"    {old}\n      -> {new}")
    else:
        print("\n  modules.json already compatible")

    # sentence_bert_config.json is passed straight into Transformer.__init__ as
    # keyword arguments. v5 writes keys that do not exist in v3 —
    # transformer_task, modality_config, module_output_name — and the load dies
    # with TypeError: unexpected keyword argument 'transformer_task'.
    #
    # Rewritten to the v3 surface rather than filtered, because v5 also OMITS
    # max_seq_length, and leaving it unset would silently fall back to the
    # model default of 512 while the model was trained and evaluated at 224.
    # An index built at a different sequence length is not comparable to the
    # measurement that justified building it.
    sbert = local_path / "sentence_bert_config.json"
    if sbert.exists():
        old_cfg = json.loads(sbert.read_text(encoding="utf-8"))
        v3_keys = {"max_seq_length", "do_lower_case"}
        dropped = sorted(set(old_cfg) - v3_keys)
        new_cfg = {
            "max_seq_length": int(old_cfg.get("max_seq_length", TRAIN_MAX_SEQ)),
            "do_lower_case": bool(old_cfg.get("do_lower_case", False)),
        }
        sbert.write_text(json.dumps(new_cfg, indent=1), encoding="utf-8")
        print(f"\n  rewrote sentence_bert_config.json -> {new_cfg}")
        if dropped:
            print(f"    dropped v5-only keys: {', '.join(dropped)}")

    # Module configs are splatted into their class constructors, so any key the
    # installed version does not declare is a TypeError. v5 and v3 disagree on
    # several. Rather than patch them one crash at a time, reconcile each config
    # against the signature of the class that will actually receive it.
    _RENAME = {"embedding_dimension": "word_embedding_dimension"}
    import inspect

    from sentence_transformers import models as st_models

    for m in modules:
        rel = (m.get("path") or "").strip()
        cfg_path = local_path / rel / "config.json"
        if not rel or not cfg_path.exists():
            continue
        cls = getattr(st_models, m["type"].rsplit(".", 1)[-1], None)
        if cls is None:
            continue
        accepted = set(inspect.signature(cls.__init__).parameters) - {"self"}

        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        fixed, dropped = {}, []
        for k, v in cfg.items():
            key = _RENAME.get(k, k)
            if key in accepted:
                fixed[key] = v
            else:
                dropped.append(k)
        if dropped or fixed != cfg:
            cfg_path.write_text(json.dumps(fixed, indent=1), encoding="utf-8")
            print(f"\n  reconciled {rel}/config.json against "
                  f"{cls.__name__}.__init__")
            for k in dropped:
                print(f"    dropped unsupported key: {k}")
            for old_k, new_k in _RENAME.items():
                if old_k in cfg and new_k in fixed:
                    print(f"    renamed {old_k} -> {new_k}")

    # Load it, and prove it is actually the tuned weights rather than the base
    # model silently falling back.
    print("\n  verifying …")
    import numpy as np
    from sentence_transformers import SentenceTransformer

    tuned = SentenceTransformer(str(local_path), device="cpu")
    base = SentenceTransformer("intfloat/multilingual-e5-base", device="cpu")
    print(f"    modules : {[type(x).__name__ for x in tuned]}")
    print(f"    dim     : {tuned.get_sentence_embedding_dimension()}")

    probe = "query: Can the Court regulate its own procedures?"
    a = base.encode([probe], normalize_embeddings=True)[0]
    b = tuned.encode([probe], normalize_embeddings=True)[0]
    dist = float(np.linalg.norm(a - b))
    print(f"    L2 distance from base: {dist:.4f}")
    if dist < 0.01:
        raise SystemExit(
            "the tuned model embeds identically to the base model — the "
            "fine-tuned weights did not load"
        )
    print("    tuned weights confirmed loaded (differs from base)")
    print(f"\n  ready: {local_path}\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Fetch and adapt the tuned model.")
    p.add_argument("--repo", default=DEFAULT_REPO)
    p.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    a = p.parse_args()
    raise SystemExit(main(a.repo, a.dest))
