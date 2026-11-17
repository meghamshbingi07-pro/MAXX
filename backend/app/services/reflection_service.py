import json
import logging
import math
import re
from datetime import datetime
 
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, func
 
from app.core.config import settings
from app.models.reflection import Reflection
from app.models.memory import Memory
from app.services.memory_service import MemoryService, _parse_embedding
from app.services.llm_service import generate_response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = True

# Minimum new memories required before reflection generation fires.
# Per ADR-044 / Phase 2.2 design: event-driven, not time-based.
REFLECTION_TRIGGER_THRESHOLD: int = 10
 
# Fixed batch size for chronological batching.
# Semantic clustering is deferred to a later phase.
REFLECTION_BATCH_SIZE: int = 10
 
# Baseline dedup threshold — may need recalibration for reflection
# embeddings, which are more uniform (LLM-generated) than raw memory text.
REFLECTION_DEDUP_THRESHOLD: float = getattr(
    settings, "REFLECTION_DEDUP_THRESHOLD", settings.DEDUP_THRESHOLD
)
 
# Prompt used for each batch of memories sent to the LLM.
# Requirements it must satisfy:
#   - third-person voice only (consistent with memory voice guard)
#   - structured JSON output, no markdown fences
#   - confidence: float 0.0–1.0, representing inference quality
#   - importance: float > 0, representing how significant the abstraction is
#   - source_memory_ids: list[int] citing only IDs from the provided batch
#   - no hallucinated memory IDs
_REFLECTION_PROMPT_TEMPLATE = """\
You are a cognitive memory system analyzing a user's stored memories to produce \
higher-order inferences.
 
Below is a numbered list of memories. Each memory has an ID and content.
 
{memory_block}
 
Your task:
Identify patterns, habits, goals, or meaningful abstractions that can be inferred \
from these memories. Produce 1 to 5 reflections. Each reflection must:
- Be a single, clear third-person statement about the user (e.g. "The user tends to...")
- Only be inferable from the provided memories — do not invent facts
- Be more abstract than any single memory
- Cite the IDs of the memories it was inferred from
 
Respond with ONLY a JSON array. No explanation. No markdown. No preamble.
Each element must have exactly these fields:
  "content": string
  "confidence": float between 0.0 and 1.0 (your confidence in this inference)
  "importance": float between 0.5 and 5.0 (how significant this abstraction is)
  "source_memory_ids": list of integer memory IDs from the list above
 
Example (do not copy this content — produce your own):
[
  {{
    "content": "The user consistently prioritises technical depth over surface-level solutions.",
    "confidence": 0.82,
    "importance": 2.5,
    "source_memory_ids": [3, 7, 12]
  }}
]
"""
 
# Regex to strip markdown code fences if the model ignores the no-fence instruction.
_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
 
 
def _strip_fences(raw: str) -> str:
    """Remove markdown code fences that local models sometimes emit anyway."""
    match = _FENCE_RE.search(raw)
    return match.group(1).strip() if match else raw.strip()
 
 
def _batch_memories(memories: list[Memory], batch_size: int) -> list[list[Memory]]:
    """Deterministic chronological batching — no clustering."""
    return [
        memories[i : i + batch_size]
        for i in range(0, len(memories), batch_size)
    ]
 
 
def _format_memory_block(batch: list[Memory]) -> str:
    """Format a batch of Memory objects into the numbered block for the prompt."""
    lines = []
    for m in batch:
        lines.append(f"[ID:{m.id}] {m.content}")
    return "\n".join(lines)
 
 
def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
 
 
def _parse_candidates(raw_output: str, valid_ids: set[int]) -> list[dict]:
    """
    Parse LLM JSON output into validated candidate dicts.
 
    Skips any candidate that:
      - is missing required fields
      - has a source_memory_id that doesn't appear in valid_ids
        (guards against hallucinated IDs)
      - produces a non-parseable number for confidence or importance
 
    Clamps confidence to [0.0, 1.0] and importance to [0.5, 5.0].
    Does NOT raise — bad candidates are skipped and logged.
    """
    cleaned = _strip_fences(raw_output)
    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"[REFLECTION] JSON parse failed: {e}\nRaw output:\n{raw_output}")
        return []
 
    if not isinstance(items, list):
        print(f"[REFLECTION] Expected JSON array, got {type(items).__name__}")
        return []
 
    candidates = []
    for i, item in enumerate(items):
        try:
            content = str(item["content"]).strip()
            confidence = _clamp(float(item["confidence"]), 0.0, 1.0)
            importance = _clamp(float(item["importance"]), 0.5, 5.0)
            source_ids = [int(x) for x in item["source_memory_ids"]]
        except (KeyError, TypeError, ValueError) as e:
            print(f"[REFLECTION] Skipping malformed candidate {i}: {e}")
            continue
 
        if not content:
            print(f"[REFLECTION] Skipping candidate {i}: empty content")
            continue
 
        hallucinated = [mid for mid in source_ids if mid not in valid_ids]
        if hallucinated:
            print(
                f"[REFLECTION] Skipping candidate {i}: "
                f"hallucinated memory IDs {hallucinated}"
            )
            continue
 
        candidates.append({
            "content": content,
            "confidence": confidence,
            "importance": importance,
            "source_memory_ids": source_ids,
        })
 
    return candidates
 
 
class ReflectionService:
 
    def __init__(self):
        self.memory_service = MemoryService()
 
    # ------------------------------------------------------------------
    # Trigger
    # ------------------------------------------------------------------
 
    async def maybe_trigger_reflections(self, db: AsyncSession) -> dict:
        """
        Check whether reflection generation should fire this turn.
 
        Fires if and only if new-memory count >= REFLECTION_TRIGGER_THRESHOLD.
        Returns a summary dict for debug logging; callers can discard it.
        """
        new_memories = await self.get_new_memories_since_last_reflection(db)
        count = len(new_memories)
 
        if count < REFLECTION_TRIGGER_THRESHOLD:
            logger.info(
                "[REFLECTION] Trigger skipped — %s/%s new memories.",
                count,
                REFLECTION_TRIGGER_THRESHOLD,
            )
            return {"triggered": False, "new_memory_count": count}
 
        logger.info(
            "[REFLECTION] Trigger fired — %s new memories, generating reflections.",
            count,
        )
        results = await self._run_reflection_cycle(new_memories, db)
        return {
            "triggered": True,
            "new_memory_count": count,
            "batches": len(results),
            "candidates_stored": sum(r["stored"] for r in results),
            "candidates_merged": sum(r["merged"] for r in results),
            "candidates_skipped": sum(r["skipped"] for r in results),
        }
 
    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
 
    async def generate_reflection_candidates(
        self,
        memories: list[Memory],
    ) -> list[dict]:
        """
        Generate reflection candidates from a single batch of Memory objects.
 
        Calls the LLM once per batch, parses and validates the JSON response,
        then returns a list of candidate dicts shaped as:
            {
                "content": str,
                "confidence": float,    # clamped to [0.0, 1.0]
                "importance": float,    # clamped to [0.5, 5.0]
                "source_memory_ids": list[int],
            }
 
        Never raises — returns empty list on any LLM or parse failure.
        """
        if not memories:
            return []
 
        valid_ids = {m.id for m in memories}
        memory_block = _format_memory_block(memories)
        prompt = _REFLECTION_PROMPT_TEMPLATE.format(memory_block=memory_block)
 
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a memory analysis system. "
                    "You respond ONLY with valid JSON arrays. "
                    "No markdown. No explanation. No preamble."
                ),
            },
            {"role": "user", "content": prompt},
        ]
 
        try:
            raw_output = await generate_response(messages)
        except Exception as e:
            print(f"[REFLECTION] LLM call failed: {e}")
            return []
 
        candidates = _parse_candidates(raw_output, valid_ids)
        print(
            f"[REFLECTION] Batch ({len(memories)} memories) → "
            f"{len(candidates)} valid candidates."
        )
        return candidates
 
    # ------------------------------------------------------------------
    # Full cycle
    # ------------------------------------------------------------------
 
    async def _run_reflection_cycle(
        self,
        memories: list[Memory],
        db: AsyncSession,
    ) -> list[dict]:
        """
        Batch memories, generate candidates per batch, persist each one.
        Returns per-batch summary dicts for logging.
        """
        batches = _batch_memories(memories, REFLECTION_BATCH_SIZE)
        batch_results = []
 
        for batch_index, batch in enumerate(batches):
            print(
                f"[REFLECTION] Processing batch "
                f"{batch_index + 1}/{len(batches)} "
                f"({len(batch)} memories)"
            )
            candidates = await self.generate_reflection_candidates(batch)
 
            stored = merged = skipped = 0
            for candidate in candidates:
                try:
                    result = await self.store_reflection(
                        content=candidate["content"],
                        confidence=candidate["confidence"],
                        importance=candidate["importance"],
                        evidence_ids=candidate["source_memory_ids"],
                        db=db,
                    )
                    if result["status"] == "stored":
                        stored += 1
                    elif result["status"] == "merged":
                        merged += 1
                except Exception as e:
                    print(f"[REFLECTION] store_reflection failed: {e}")
                    skipped += 1
 
            batch_results.append({
                "batch": batch_index + 1,
                "memories": len(batch),
                "candidates": len(candidates),
                "stored": stored,
                "merged": merged,
                "skipped": skipped,
            })
 
        return batch_results
 
    # ------------------------------------------------------------------
    # Persistence (trigger path)
    # ------------------------------------------------------------------
 
    async def get_new_memories_since_last_reflection(
        self,
        db: AsyncSession,
    ) -> list[Memory]:
        """Stateless watermark query — no counter table, per ADR-044."""
        max_result = await db.execute(
            select(func.max(Reflection.created_at))
        )
        last_reflection_time = max_result.scalar()
 
        query = select(Memory)
        if last_reflection_time is not None:
            query = query.where(Memory.created_at > last_reflection_time)
        query = query.order_by(Memory.created_at.asc())
 
        result = await db.execute(query)
        return list(result.scalars().all())
 
    async def store_reflection(
        self,
        content: str,
        confidence: float,
        importance: float,
        evidence_ids: list[int],
        db: AsyncSession,
    ) -> dict:
        """
        Store a reflection with semantic dedup per ADR-044 merge semantics:
          - match: keep content/confidence/embedding frozen, union provenance
          - no match: insert new row + provenance links
        """
        embedding = await self.memory_service.generate_embedding(content)
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
 
        nearest = await db.execute(
            text(
                """SELECT id, content, confidence, importance,
                          embedding <=> CAST(:embedding AS vector) AS distance
                   FROM reflections
                   ORDER BY distance ASC
                   LIMIT 1"""
            ),
            {"embedding": embedding_str},
        )
        existing = nearest.mappings().first()
 
        if existing and existing["distance"] < REFLECTION_DEDUP_THRESHOLD:
            reflection_id = existing["id"]
            print(
                f"[REFLECTION] Merge — reflection {reflection_id} "
                f"(distance={existing['distance']:.4f})"
            )
            for memory_id in evidence_ids:
                await db.execute(
                    text(
                        """INSERT INTO reflection_memory_links
                               (reflection_id, memory_id)
                           VALUES (:reflection_id, :memory_id)
                           ON CONFLICT DO NOTHING"""
                    ),
                    {"reflection_id": reflection_id, "memory_id": memory_id},
                )
            await db.commit()
            return {
                "status": "merged",
                "reflection_id": reflection_id,
                "content": existing["content"],
                "confidence": float(existing["confidence"]),
                "importance": float(existing["importance"]),
                "evidence_ids": evidence_ids,
            }
 
        result = await db.execute(
            text(
                """INSERT INTO reflections
                       (content, importance, confidence, embedding, created_at)
                   VALUES
                       (:content, :importance, :confidence,
                        CAST(:embedding AS vector), :created_at)
                   RETURNING id"""
            ),
            {
                "content": content,
                "importance": importance,
                "confidence": confidence,
                "embedding": embedding_str,
                "created_at": datetime.now(),
            },
        )
        reflection_id = result.mappings().first()["id"]
 
        for memory_id in evidence_ids:
            await db.execute(
                text(
                    """INSERT INTO reflection_memory_links
                           (reflection_id, memory_id)
                       VALUES (:reflection_id, :memory_id)
                       ON CONFLICT DO NOTHING"""
                ),
                {"reflection_id": reflection_id, "memory_id": memory_id},
            )
 
        await db.commit()
        logger.info("[REFLECTION] Stored id=%s: %s", reflection_id, content[:80])
        return {
            "status": "stored",
            "reflection_id": reflection_id,
            "content": content,
            "confidence": confidence,
            "importance": importance,
            "evidence_ids": evidence_ids,
        }
 
    # ------------------------------------------------------------------
    # Retrieval (called by context_service)
    # ------------------------------------------------------------------
 
    async def search_reflections(
        self,
        query: str,
        db: AsyncSession,
        limit: int = 5,
        similarity_threshold: float = 0.55,
    ) -> tuple[list[dict], list[dict]]:
        """Search reflections by semantic similarity.
 
        Returns (candidates, debug_reflections).
        candidates are shaped for the global MMR pass in context_service.
        """
        query_embedding = await self.memory_service.generate_embedding(query)
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
 
        result = await db.execute(
            text(
                """SELECT r.*,
                          embedding <=> CAST(:embedding AS vector) AS distance,
                          COUNT(l.memory_id) AS provenance_count
                   FROM reflections r
                   LEFT JOIN reflection_memory_links l ON l.reflection_id = r.id
                   GROUP BY r.id
                   ORDER BY distance ASC
                   LIMIT :limit"""
            ),
            {"embedding": embedding_str, "limit": limit},
        )
        rows = result.mappings().all()
 
        candidates = []
        debug_reflections = []
 
        for row in rows:
            distance = float(row["distance"])
            similarity_score = 1.0 - distance
 
            if similarity_score < similarity_threshold:
                continue
 
            prov_count = int(row["provenance_count"] or 0)
            confidence_score = float(row["confidence"] or 0.0)
            importance_raw = float(row["importance"] or 0.0)
            importance_score = 1.0 - math.exp(-importance_raw / 5.0)
            evidence_strength = 1.0 - math.exp(-prov_count / 3.0)
 
            reflection_score = (
                similarity_score * 0.50
                + confidence_score * 0.25
                + importance_score * 0.15
                + evidence_strength * 0.10
            )
 
            reflection_data = {
                k: v
                for k, v in dict(row).items()
                if k not in ("distance", "provenance_count")
            }
            reflection = Reflection(**reflection_data)
            parsed_embedding = _parse_embedding(reflection.embedding)
 
            candidates.append({
                "object_type": "reflection",
                "reflection": reflection,
                "similarity": similarity_score,
                "retrieval_score": reflection_score,
                "parsed_embedding": parsed_embedding,
                "provenance_count": prov_count,
            })
            debug_reflections.append({
                "id": reflection.id,
                "content": reflection.content,
                "similarity": round(similarity_score, 4),
                "retrieval_score": round(reflection_score, 4),
                "confidence": confidence_score,
                "importance": importance_raw,
                "provenance_count": prov_count,
                "evidence_strength": round(evidence_strength, 4),
            })
 
        return candidates, debug_reflections
 
    async def get_reflections_for_memory(
        self,
        memory_id: int,
        db: AsyncSession,
    ) -> list[Reflection]:
        """All reflections citing a specific memory as evidence."""
        result = await db.execute(
            text(
                """SELECT r.*
                   FROM reflections r
                   JOIN reflection_memory_links l ON l.reflection_id = r.id
                   WHERE l.memory_id = :memory_id
                   ORDER BY r.created_at DESC"""
            ),
            {"memory_id": memory_id},
        )
        return [Reflection(**dict(row)) for row in result.mappings().all()]