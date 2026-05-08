from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.constants import CaseType, Province


class Citation(BaseModel):
    court: str | None = None
    case_number: str | None = None
    section: str | None = None
    chunk_text: str | None = None


class ChatMessage(BaseModel):
    role: str  # user | assistant
    content: str
    citations: list[Citation] = []
    confidence: float | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChatSessionDocument(BaseModel):
    id: str = Field(alias="_id")
    session_id: str
    client_id: str
    case_id: str | None = None
    case_type: CaseType | None = None
    province: Province | None = None
    messages: list[ChatMessage] = []
    # Serialized LangGraph checkpointer — populated when AI is wired in
    langgraph_checkpoint: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}
