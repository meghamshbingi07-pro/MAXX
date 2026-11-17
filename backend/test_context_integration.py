import asyncio
from app.db.session import get_session
from app.services.context_service import ContextService
from app.services.memory_service import MemoryService
from app.services.reflection_service import ReflectionService
from sqlalchemy import text

async def run_test_scenario(db, query, memory_id_to_link=None, reflection_content=None, debug_label=""):
    print(f"\n--- Running Scenario: {debug_label} ---")
    context_service = ContextService()
    memory_service = MemoryService()
    reflection_service = ReflectionService()

    if reflection_content:
        print(f"Inserting reflection: {reflection_content[:50]}...")
        evidence_ids = [memory_id_to_link] if memory_id_to_link is not None else []
        reflect_result = await reflection_service.store_reflection(
            content=reflection_content,
            confidence=0.8,
            importance=1.0,
            evidence_ids=evidence_ids,
            db=db,
        )
        print(f"Reflection stored/merged: {reflect_result}")

    relevant_context, debug_info, _ = await context_service.build_context(
        db=db,
        query=query,
        memory_limit=20,
        intent="general",
    )

    print("\nRelevant Context:")
    for item in relevant_context:
        print(f"- {item}")

    print("\nDebug Info (Sorted by retrieval_score descending):")
    debug_info_sorted = sorted(debug_info, key=lambda x: x.get('retrieval_score', 0), reverse=True)
    for item in debug_info_sorted:
        obj_type = "memory" if "memory_type" in item else "reflection"
        print(f"[{item.get('retrieval_score',0):.4f} {obj_type[:4]}] {item['content'][:70]}...")

    print("\n--- Scenario Complete ---")
    return relevant_context, debug_info

async def main():
    async for db in get_session():

        # Clean up existing reflections before tests to ensure a clean slate
        print("Clearing existing reflections...")
        await db.execute(text("DELETE FROM reflection_memory_links"))
        await db.execute(text("DELETE FROM reflections"))
        await db.commit()
        print("Reflections cleared.")

        # Test 1: No reflections in DB, existing memories behave as before
        print("\n### Running Test 1: No reflections ###")
        query1 = "What are my goals?"
        context1, debug1 = await run_test_scenario(db, query1, debug_label="Test 1: Only Memories")

        assert all("memory_type" in item for item in debug1), "Test 1 failed: Expected only memory candidates"
        assert not any(item.get("object_type") == "reflection" for item in debug1), "Test 1 failed: Unexpected reflection candidates"
        print("Test 1 passed: Only memories retrieved and processed.")

        # Test 2: Insert one reflection, retrieve both memory and reflection
        print("\n### Running Test 2: Memories + Reflection ###")
        memory_service = MemoryService()
        memories_result = await memory_service.search_memories(
            query="goals", db=db, limit=1, similarity_threshold=0.0
        )
        existing_memory_id = memories_result[0][0].id if memories_result[0] else None
        print(f"Using existing memory ID for reflection evidence: {existing_memory_id}")

        query2 = "What is the AI's long term vision and my work?"
        reflection_content = "User is building MAXX as a cognitive AI platform focused on long-term contextual continuity and reducing memory contamination."

        context2, debug2 = await run_test_scenario(
            db, query2, memory_id_to_link=existing_memory_id,
            reflection_content=reflection_content,
            debug_label="Test 2: Memories + Reflection"
        )

        print(f"\n[DIAGNOSTIC] Final context has {len(context2)} items:")
        for i, item in enumerate(context2):
            print(f"  [{i}] {item[:80]}")

        # Validate via context content
        memory_in_context = any(
            "goal" in item.lower() or "memory" in item.lower()
            for item in context2
        )
        reflection_in_context = any(reflection_content in item for item in context2)
        if not reflection_in_context:
            print("[DIAGNOSTIC] Reflection NOT found in final context. Checking similarity threshold...")
            print("[DIAGNOSTIC] The general threshold is 0.70 — reflection may be below this.")
        assert memory_in_context, "Test 2 failed: Expected memory-derived content in final context"
        assert reflection_in_context, "Test 2 failed: Expected reflection content in final context"
        print("Test 2 passed: Both memory and reflection content confirmed in final context.")

        # Final cleanup
        print("\nFinal cleanup: Deleting test reflections...")
        await db.execute(text("DELETE FROM reflection_memory_links"))
        await db.execute(text("DELETE FROM reflections"))
        await db.commit()
        print("Cleanup complete.")

asyncio.run(main())