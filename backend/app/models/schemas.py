from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str


class MemoryRequest(BaseModel):
    user_id: str
    memory: str


class MemoryResponse(BaseModel):
    success: bool
    message: str
