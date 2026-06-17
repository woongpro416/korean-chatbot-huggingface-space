from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Language(str, Enum):
    korean = "ko"
    english = "en"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    language: Language = Field(Language.korean)
    max_length: int = Field(128, ge=50, le=500)
    temperature: float = Field(0.8, ge=0.1, le=1.5)


class ChatResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    user_message: str
    bot_response: str
    language: str
    model_used: str
    tokens_generated: Optional[int] = None
