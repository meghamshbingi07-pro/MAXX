import logging

from fastapi import FastAPI

from app.core.config import settings

from app.api.routes.chat import router as chat_router
from app.api.routes.conversation import router as conversation_router
from app.api.routes.memory import router as memory_router
from app.api.routes.health import router as health_router
from app.api.routes.db_test import router as db_test_router

from app.core.exceptions import (
    MAXXException,
    maxx_exception_handler,
)
from app.db.init_db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
    force=True,
)

logging.getLogger("app").setLevel(logging.INFO)
logging.getLogger("app").propagate = True

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0"
)

app.add_exception_handler(
    MAXXException,
    maxx_exception_handler,
)


@app.on_event("startup")
async def startup():
    await init_db()


app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(health_router)
app.include_router(db_test_router)
app.include_router(conversation_router)


@app.get("/")
def root():
    return {
        "message": "MAXX backend running"
    }