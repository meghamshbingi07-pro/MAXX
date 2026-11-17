from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.conversation_service import (
    create_conversation,
    add_message,
    get_conversation_messages,
)

router = APIRouter()


@router.post("/conversation")
async def new_conversation(
    db: AsyncSession = Depends(get_session),
):
    conversation = await create_conversation(db)

    return {
        "id": conversation.id,
        "title": conversation.title,
    }


@router.post("/conversation/{conversation_id}/message")
async def create_message(
    conversation_id: int,
    role: str,
    content: str,
    db: AsyncSession = Depends(get_session),
):
    message = await add_message(
        db=db,
        conversation_id=conversation_id,
        role=role,
        content=content,
    )

    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": message.content,
    }


@router.get("/conversation/{conversation_id}/messages")
async def get_messages(
    conversation_id: int,
    db: AsyncSession = Depends(get_session),
):
    messages = await get_conversation_messages(
        db=db,
        conversation_id=conversation_id,
    )

    return [
        {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at,
        }
        for msg in messages
    ]