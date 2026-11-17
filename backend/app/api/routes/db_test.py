from fastapi import APIRouter
from sqlalchemy import text

from app.db.session import AsyncSessionLocal

router = APIRouter(
    prefix="/db-test",
    tags=["Database"]
)


@router.get("")
async def test_db():

    async with AsyncSessionLocal() as session:

        result = await session.execute(
            text("SELECT 1")
        )

        return {
            "database": "connected",
            "result": result.scalar()
        }
