from datetime import datetime

from pydantic import BaseModel, Field

from app.core.constants import DocumentTemplate


class DocumentDocument(BaseModel):
    id: str = Field(alias="_id")
    case_id: str
    client_id: str
    template_type: DocumentTemplate
    title: str
    fields: dict = {}        # field values used to fill the template
    file_path: str | None = None   # local path to generated PDF
    status: str = "pending"  # pending | generated | failed
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}
