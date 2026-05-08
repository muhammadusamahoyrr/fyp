import pathlib

import chromadb
from chromadb import ClientAPI

_client: ClientAPI | None = None

COLLECTIONS = [
    "civil_collection",
    "criminal_collection",
    "family_collection",
    "constitutional_collection",
    "statutes_collection",
    "judgments_collection",
    "lawyers_collection",
]

_CHROMA_PATH = pathlib.Path(__file__).resolve().parents[2] / "chroma_data"


def connect_chroma() -> None:
    global _client
    _CHROMA_PATH.mkdir(exist_ok=True)
    _client = chromadb.PersistentClient(path=str(_CHROMA_PATH))


def close_chroma() -> None:
    global _client
    _client = None


def get_chroma() -> ClientAPI:
    if _client is None:
        raise RuntimeError("ChromaDB client not initialized — call connect_chroma() first")
    return _client


def get_collection(name: str):
    if name not in COLLECTIONS:
        raise ValueError(f"Unknown collection '{name}'. Valid: {COLLECTIONS}")
    return get_chroma().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )
