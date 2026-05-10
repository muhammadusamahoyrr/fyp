"""
schemas.py — Pydantic v2 typed models for the Attorney.AI pipeline.

Replaces plain dict passing between nodes.  Every node that produces
retrieval hits, chunks, or routing decisions should validate against
these models so that silent key-miss bugs surface immediately.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────

class CaseType(str, Enum):
    CIVIL          = "civil"
    CRIMINAL       = "criminal"
    FAMILY         = "family"
    CONSTITUTIONAL = "constitutional"
    UNKNOWN        = "unknown"


class Province(str, Enum):
    PUNJAB      = "punjab"
    SINDH       = "sindh"
    KPK         = "kpk"
    BALOCHISTAN = "balochistan"
    FEDERAL     = "federal"
    UNKNOWN     = "unknown"


class RoutingMode(str, Enum):
    """How retrieval should be performed."""
    SINGLE = "single"   # single known collection
    HYBRID = "hybrid"   # unknown case_type → search across collections


# ── Core Chunk Model ──────────────────────────────────────────────────────────

class LawChunk(BaseModel):
    """A single law statute chunk returned from the vector store."""
    content:        str
    statute:        str  = ""
    section_number: str  = ""
    source_file:    str  = ""
    chunk_id:       str  = ""
    province:       str  = "federal"
    law_type:       str  = ""

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, d: dict) -> "LawChunk":
        return cls(**{k: v for k, v in d.items() if k in cls.model_fields})


# ── Retrieval Hit (scored chunk) ──────────────────────────────────────────────

class RetrievalHit(BaseModel):
    """A chunk annotated with a relevance score after grading."""
    chunk:           LawChunk
    relevance_score: float = Field(ge=0.0, le=1.0, default=0.0)
    is_relevant:     bool  = False


# ── Classifier Result (keyword-based, no LLM) ────────────────────────────────

class ClassifierResult(BaseModel):
    """Output of classifier_node — fast keyword-based routing decision."""
    case_type:  CaseType
    confidence: float = Field(ge=0.0, le=1.0)
    # Which collections to query (set to multiple if confidence is low)
    routing_mode: RoutingMode = RoutingMode.SINGLE
    matched_signals: list[str] = Field(default_factory=list)


# ── Triage Result (LLM-based, richer) ────────────────────────────────────────

class TriageResult(BaseModel):
    """Full triage output from the LLM-based triage_node."""
    category:             str    # "legal" | "off_topic"
    language:             str    # "en" | "ur" | "roman_urdu"
    normalized_query:     str
    case_type:            CaseType
    case_type_confidence: float = Field(ge=0.0, le=1.0)
    complexity:           str   # "simple" | "complex"
    urgency:              str   # "low" | "medium" | "high" | "critical"
    province:             Province
    known_facts:          list[str] = Field(default_factory=list)
    reason:               str  = ""


# ── Law Graph Node (for networkx hop-2) ──────────────────────────────────────

class GraphNeighbor(BaseModel):
    """An edge in the statute cross-reference graph."""
    target_id:     str
    relation_type: str   # "cite" | "ref" | "amend" | "defined_by"
    weight:        float = 1.0


class LawNode(BaseModel):
    """A node in the law graph representing a statute section."""
    node_id:        str
    statute:        str
    section_number: str
    province:       str       = "federal"
    law_type:       str       = ""
    neighbors:      list[GraphNeighbor] = Field(default_factory=list)
