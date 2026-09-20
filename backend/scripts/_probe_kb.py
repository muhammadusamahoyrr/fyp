import os, sys
from pathlib import Path
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import sqlite3
# Read the real store WITHOUT a Chroma client, so nothing can write to it.
real = BACKEND / "chroma_data" / "chroma.sqlite3"
copy = Path(os.environ["SCRATCH"]) / "chroma_copy" / "chroma.sqlite3"
for label, path in (("REAL ", real), ("COPY ", copy)):
    con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    cols = con.execute("select name from collections order by name").fetchall()
    n = con.execute("select count(*) from embeddings").fetchone()[0]
    meta = con.execute("select count(*) from embedding_metadata").fetchone()[0]
    print(f"{label} collections={len(cols)} embeddings={n:,} metadata_rows={meta:,}")
    print(f"       {[c[0] for c in cols]}")
    con.close()
