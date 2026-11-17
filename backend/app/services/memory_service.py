import ast
import logging
import math
from datetime import datetime

import httpx
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Memory

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = True

OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "mxbai-embed-large"
DEDUP_THRESHOLD = 0.2  # cosine distance — lower = more similar


def _parse_embedding(value) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [float(x) for x in value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, (list, tuple)):
                return [float(x) for x in parsed]
        except (ValueError, SyntaxError):
            pass
        try:
            return [float(x) for x in text.split(",") if x.strip()]
        except ValueError:
            return []
    return []


def _cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0

    if len(a) != len(b):
        size = min(len(a), len(b))
        a = a[:size]
        b = b[:size]

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_importance_from_salience(salience: float, memory_type: str = "general") -> float:
    base = max(salience, 0.0)
    type_multiplier = {
        "goal": 1.15,
        "preference": 1.10,
        "project": 1.08,
        "fact": 1.05,
        "general": 1.0,
    }.get(memory_type, 1.0)
    return round(min(base * type_multiplier, 5.0), 2)


class MemoryService:

    async def generate_embedding(self, content: str) -> list[float]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OLLAMA_EMBED_URL,
                json={"model": EMBED_MODEL, "prompt": content},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()["embedding"]

    async def store_memory(
        self,
        content: str,
        memory_type: str = "general",
        conversation_id: int | None = None,
        salience: float = 0.0,
        importance: float = 1.0,
        db: AsyncSession = None,
    ) -> dict:
        embedding = await self.generate_embedding(content)
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        duplicate_check = await db.execute(
            text(
                "SELECT *, "
                "embedding <=> CAST(:embedding AS vector) AS distance "
                "FROM memories "
                "ORDER BY distance ASC "
                "LIMIT 1"
            ),
            {"embedding": embedding_str},
        )
        existing = duplicate_check.mappings().first()

        if existing and existing["distance"] < DEDUP_THRESHOLD:
            # reinforce importance on duplicate detection
            await db.execute(
                text(
                    "UPDATE memories SET importance = COALESCE(importance, 0) + :inc WHERE id = :id"
                ),
                {"inc": 1.0, "id": existing["id"]},
            )
            await db.commit()

            updated = await db.execute(
                text(
                    "SELECT id, content, memory_type, salience, importance, retrieval_count, last_accessed, created_at FROM memories WHERE id = :id"
                ),
                {"id": existing["id"]},
            )
            row = updated.mappings().first()

            return {
                "status": "duplicate",
                "id": row["id"],
                "content": row["content"],
                "memory_type": row["memory_type"],
                "salience": row["salience"],
                "importance": row["importance"],
                "retrieval_count": row["retrieval_count"],
                "last_accessed": row["last_accessed"],
                "created_at": row["created_at"],
                "distance": existing["distance"],
            }

        memory = Memory(
            content=content,
            memory_type=memory_type,
            conversation_id=conversation_id,
            embedding=embedding,
            salience=salience,
            importance=importance,
        )
        db.add(memory)
        await db.commit()
        await db.refresh(memory)

        return {
            "status": "stored",
            "id": memory.id,
            "content": memory.content,
            "memory_type": memory.memory_type,
        }

    async def search_memories(
        self,
        query: str,
        db: AsyncSession,
        limit: int = 20,
        similarity_threshold: float = 0.55,
        memory_types: list[str] | None = None,
        mmr_limit: int | None = None,
        skip_mmr: bool = True,
    ):
        query_embedding = await self.generate_embedding(query)
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        result = await db.execute(
            text(
                """
            SELECT *,
                   embedding <=> CAST(:embedding AS vector) AS distance
            FROM memories
            ORDER BY distance ASC
            LIMIT :limit
            """
            ),
            {
                "embedding": embedding_str,
                "limit": limit,
            },
        )

        rows = result.mappings().all()
        debug_memories = []
        ranked_memories = []

        for row in rows:
            memory_data = dict(row)
            distance = float(memory_data.pop("distance", 0.0))
            memory = Memory(**memory_data)
            memory_type = getattr(memory, "memory_type", "general")
            if memory_types and memory_type not in memory_types:
                continue

            similarity_score = 1 - distance
            salience = float(getattr(memory, "salience", 0.0) or 0.0)
            importance = float(getattr(memory, "importance", 0.0) or 0.0)

            importance_score = min(importance / 10.0, 1.0)
            retrieval_score = (
                similarity_score * 0.7
                + salience * 0.2
                + importance_score * 0.1
            )

            parsed_embedding = _parse_embedding(getattr(memory, "embedding", None))
            ranked_memories.append({
                "object_type": "memory",
                "memory": memory,
                "similarity": similarity_score,
                "retrieval_score": retrieval_score,
                "parsed_embedding": parsed_embedding,
            })

        ranked_memories.sort(
            key=lambda x: x["retrieval_score"],
            reverse=True,
        )

        relevant_memories = []
        passed_ids = []

        for item in ranked_memories:
            memory = item["memory"]
            similarity_score = item["similarity"]
            retrieval_score = item["retrieval_score"]

            debug_memories.append({
                "id": memory.id,
                "content": memory.content,
                "memory_type": memory.memory_type,
                "similarity": round(similarity_score, 4),
                "retrieval_score": round(retrieval_score, 4),
                "salience": getattr(memory, "salience", 0.0),
                "importance": getattr(memory, "importance", 0.0),
                "retrieval_count": getattr(memory, "retrieval_count", 0),
                "last_accessed": getattr(memory, "last_accessed", None),
            })

            if (
                similarity_score >= similarity_threshold
                or retrieval_score >= 0.55
            ):
                relevant_memories.append(item)
                passed_ids.append(memory.id)

        if passed_ids:
            await db.execute(
                update(Memory)
                .where(Memory.id.in_(passed_ids))
                .values(
                    retrieval_count=Memory.retrieval_count + 1,
                    last_accessed=datetime.utcnow(),
                )
            )
            await db.commit()

        print("===== MEMORY RETRIEVAL DEBUG =====", flush=True)
        for item in debug_memories:
            print(f"[{item['similarity']}] {item['content']}", flush=True)
        print("==================================", flush=True)
        logger.info("===== MEMORY RETRIEVAL DEBUG =====")
        for item in debug_memories:
            logger.info("[%s] %s", item["similarity"], item["content"])
        logger.info("==================================")

        return relevant_memories, debug_memories