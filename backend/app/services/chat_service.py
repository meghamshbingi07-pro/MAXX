import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession
 
from app.services.conversation_service import (
    create_conversation,
    add_message,
)
from app.services.context_service import ContextService
from app.services.memory_extraction_service import MemoryExtractionService
from app.services.memory_intent_service import MemoryIntentService
from app.services.memory_service import MemoryService, compute_importance_from_salience
from app.services.reflection_service import ReflectionService
from app.services.llm_service import generate_response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = True

context_service = ContextService()


def _append_debug_log(debug_logs: list[str], message: str) -> None:
    debug_logs.append(message)
    print(message, flush=True)
    logger.info(message)
extraction_service = MemoryExtractionService()
intent_service = MemoryIntentService()
memory_service = MemoryService()
reflection_service = ReflectionService()
 
 
def build_system_prompt(memories: list[str]) -> str:
    base = """
You are MAXX, a persistent AI assistant with long-term memory.
 
The memory section below contains factual information you know about the user.
 
When a user asks about themselves, their preferences, goals, projects, history, or previous information they have shared, you MUST use these memories to answer.
 
If a memory directly answers the user's question, prefer the memory over generic assumptions.
 
Do not say "I don't know" if the answer exists in memory.
 
Do not mention that memories were used.
 
When multiple memories relate to the same topic, combine them into a single answer.
 
For example:
 
If multiple goal memories are retrieved, summarize all of them rather than selecting only one.
"""
 
    if not memories:
        return base
 
    memory_block = "\n".join(f"- {m}" for m in memories)
    return f"{base}\n\nUser Memory:\n{memory_block}"
 
 
def format_conversation_history(messages: list) -> list[dict]:
    formatted = []
    for msg in messages:
        role = msg.role if hasattr(msg, "role") else msg["role"]
        content = msg.content if hasattr(msg, "content") else msg["content"]
        formatted.append({"role": role, "content": content})
    return formatted
 
 
async def generate_chat_response(
    db: AsyncSession,
    user_message: str,
    conversation_id: int | None = None,
):
    debug_logs: list[str] = []

    if conversation_id is None:
        conversation = await create_conversation(db)
        conversation_id = conversation.id
 
    await add_message(
        db=db,
        conversation_id=conversation_id,
        role="user",
        content=user_message,
    )
 
    # --- Memory extraction ---
    extracted = await extraction_service.extract_memories(user_message)
 
    stored_ids = []
    rejected_count = 0
 
    for memory in extracted:
        salience = memory.get("salience", 0)
        if salience < 0.70:
            continue
 
        memory_type = memory.get("memory_type", "general")
        importance = compute_importance_from_salience(salience, memory_type)
 
        result = await memory_service.store_memory(
            content=memory["content"],
            memory_type=memory_type,
            conversation_id=conversation_id,
            salience=salience,
            importance=importance,
            db=db,
        )
 
        if result["status"] == "rejected":
            rejected_count += 1
            _append_debug_log(
                debug_logs,
                f"[EXTRACTION] Memory rejected: {result['reason']}",
            )
        elif result["status"] in ("stored", "duplicate"):
            stored_ids.append(result["id"])
 
    if rejected_count:
        _append_debug_log(
            debug_logs,
            f"[EXTRACTION] {rejected_count} memory(ies) rejected this turn.",
        )
 
    # --- Reflection trigger (fires after extraction, before retrieval) ---
    # Runs only when enough new memories have accumulated since the last
    # reflection cycle. Does not block the response on failure.
    try:
        trigger_result = await reflection_service.maybe_trigger_reflections(db)
        if trigger_result["triggered"]:
            _append_debug_log(
                debug_logs,
                "[REFLECTION] Cycle complete — "
                f"stored={trigger_result['candidates_stored']} "
                f"merged={trigger_result['candidates_merged']} "
                f"skipped={trigger_result['candidates_skipped']}",
            )
    except Exception as e:
        # Reflection failure must never surface to the user or break retrieval.
        _append_debug_log(debug_logs, f"[REFLECTION] Trigger error (non-fatal): {e}")
 
    # --- Intent detection + retrieval ---
    intent = intent_service.detect_intent(user_message)
    _append_debug_log(debug_logs, f"INTENT: {intent}")
 
    relevant_memories, debug_memories, messages_history = await context_service.build_context(
        db=db,
        query=user_message,
        conversation_id=conversation_id,
        memory_limit=20,
        intent=intent,
    )
 
    # --- Response generation ---
    system_prompt = build_system_prompt(relevant_memories)
    history = format_conversation_history(messages_history)
 
    messages = (
        [{"role": "system", "content": system_prompt}]
        + history
        + [{"role": "user", "content": user_message}]
    )
 
    assistant_response = await generate_response(messages)
 
    await add_message(
        db=db,
        conversation_id=conversation_id,
        role="assistant",
        content=assistant_response,
    )
 
    return {
        "conversation_id": conversation_id,
        "response": assistant_response,
        "memories_used": relevant_memories,
        "retrieved_memories": debug_memories,
        "debug_logs": debug_logs,
    }