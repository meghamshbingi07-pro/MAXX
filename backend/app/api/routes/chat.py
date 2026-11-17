from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.db.session import get_session

from app.services.chat_service import (
    generate_chat_response,
)


router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    conversation_id: int | None = None


@router.post("/chat")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_session),
):
    response = await generate_chat_response(
        db=db,
        user_message=request.message,
        conversation_id=request.conversation_id,
    )

    return response