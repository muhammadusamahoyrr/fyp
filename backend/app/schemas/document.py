from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.core.constants import DocumentTemplate


class DocumentExtract(BaseModel):
    case_id: str
    template_type: DocumentTemplate


class DocumentGenerate(BaseModel):
    case_id: str
    template_type: DocumentTemplate
    fields: dict[str, Any] = {}   # pass {} to trigger auto-extraction


class DocumentResponse(BaseModel):
    id: str
    case_id: str
    template_type: DocumentTemplate
    title: str
    status: str
    created_at: datetime
