import asyncio
import sys
from pathlib import Path
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parent / "backend"))
from app.db.session import get_session
from app.services.memory_service import MemoryService
from app.services.reflection_service import ReflectionService

async def run_validation_tests():
    async for db in get_session():
        memory_service = MemoryService()
        reflection_service = ReflectionService()

        # --- Setup: Clear existing reflections and create some base memories ---
        print("\n--- Setting up for validation tests ---")
        await db.execute(text("DELETE FROM reflection_memory_links"))
        await db.execute(text("DELETE FROM reflections"))
        await db.execute(text("DELETE FROM memories")) # Clear memories for consistent testing
        await db.commit()

        # Create 10 dummy memories for trigger threshold (if not already present)
        for i in range(1, 11):
            await memory_service.store_memory(
                content=f"Dummy memory {i} for validation",
                memory_type="general",
                conversation_id=1, # Assuming a default conversation ID
                salience=0.5,
                importance=1.0,
                db=db,
            )
        await db.commit()
        print(f"Created 10 dummy memories. Total memories: {await db.scalar(text('SELECT COUNT(*) FROM memories'))}")

        # --- Test 1: New reflection stores importance=2.5 correctly ---
        print("\n--- Running Test 1: New reflection stores importance ---")
        content1 = "This is a new reflection with custom importance."
        importance1 = 2.5
        result1 = await reflection_service.store_reflection(
            content=content1,
            confidence=0.7,
            importance=importance1,
            evidence_ids=[],
            db=db,
        )
        assert result1["status"] == "stored"
        assert result1["content"] == content1
        assert result1["importance"] == importance1

        # Verify in DB
        stored_reflection = await db.execute(text("SELECT importance FROM reflections WHERE id = :id"), {"id": result1["reflection_id"]})
        db_importance = stored_reflection.scalar_one()
        assert db_importance == importance1
        print(f"Test 1 Passed: New reflection importance {db_importance} stored correctly.")

        # --- Test 2: Duplicate merge returns stored importance (ignores passed) ---
        print("\n--- Running Test 2: Duplicate merge returns stored importance ---")
        content2 = content1 # Use same content to trigger merge
        importance_passed_for_merge = 999.0 # This should be ignored
        result2 = await reflection_service.store_reflection(
            content=content2,
            confidence=0.8,
            importance=importance_passed_for_merge, # Should be ignored
            evidence_ids=[1, 2], # Add some evidence links
            db=db,
        )
        assert result2["status"] == "merged"
        assert result2["reflection_id"] == result1["reflection_id"]
        assert result2["importance"] == importance1 # Should be original importance

        # Verify no duplicate row and provenance link created
        reflection_count = await db.scalar(text("SELECT COUNT(*) FROM reflections WHERE content = :content"), {"content": content1})
        assert reflection_count == 1
        link_count = await db.scalar(text("SELECT COUNT(*) FROM reflection_memory_links WHERE reflection_id = :rid AND memory_id IN (1,2)"), {"rid": result1["reflection_id"]})
        assert link_count == 2
        print(f"Test 2 Passed: Duplicate merge returned stored importance ({result2['importance']}). No duplicate row, {link_count} provenance links created.")

        # --- Test 3: Retrieval returns reflection with correct importance ---
        print("\n--- Running Test 3: Retrieval returns correct importance ---")
        query = "Custom importance reflection"
        candidates, debug_reflections = await reflection_service.search_reflections(query=query, db=db, limit=1)

        assert len(candidates) > 0
        retrieved_reflection = candidates[0]["reflection"]
        assert retrieved_reflection.importance == importance1
        print(f"Test 3 Passed: Retrieved reflection has correct importance ({retrieved_reflection.importance}).")

        # --- Test 4: Regression - candidate dict format intact (check any previous reflection) ---
        print("\n--- Running Test 4: Regression - candidate dict format intact ---")
        # Search for any reflection to get a candidate dict
        any_query = "general knowledge"
        candidates_reg, _ = await reflection_service.search_reflections(query=any_query, db=db, limit=1)
        assert len(candidates_reg) > 0
        candidate_dict = candidates_reg[0]
        assert "object_type" in candidate_dict
        assert "reflection" in candidate_dict
        assert "similarity" in candidate_dict
        assert "retrieval_score" in candidate_dict
        assert "parsed_embedding" in candidate_dict
        assert "provenance_count" in candidate_dict
        print("Test 4 Passed: Candidate dict format intact.")

        print("\n--- All Validation Tests Passed! ---")

if __name__ == "__main__":
    asyncio.run(run_validation_tests())
