from app.db.base import Base
from app.db.session import engine
from sqlalchemy import text

# Import models so SQLAlchemy registers them
from app.models import *


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Ensure new columns exist for older databases
        await conn.execute(
            text(
                """
                ALTER TABLE IF EXISTS memories
                ADD COLUMN IF NOT EXISTS salience DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                ADD COLUMN IF NOT EXISTS importance DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                ADD COLUMN IF NOT EXISTS retrieval_count INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS last_accessed TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW();
                """
            )
        )
