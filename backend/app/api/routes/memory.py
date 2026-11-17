from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/memory", tags=["Memory"])
memory_service = MemoryService()


@router.post("/store")
async def store_memory(
    content: str,
    memory_type: str = "general",
    conversation_id: int | None = None,
    db: AsyncSession = Depends(get_session),
):
    return await memory_service.store_memory(
        content=content,
        memory_type=memory_type,
        conversation_id=conversation_id,
        db=db,
    )


@router.get("/search")
async def search_memories(
    query: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_session),
):
    results, debug_memories = await memory_service.search_memories(query=query, db=db, limit=limit)
    return [
        {
            "id": item["memory"].id,
            "content": item["memory"].content,
            "memory_type": item["memory"].memory_type,
        }
        for item in results
    ]