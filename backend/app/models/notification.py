from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.constants import NotificationType


class NotificationDocument(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    type: NotificationType
    title: str
    body: str
    payload: dict[str, Any] = {}
    read: bool = False
    read_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}
