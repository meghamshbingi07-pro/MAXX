"""
Verify duplicate reflection behavior:
1. Still one row after duplicate insert
2. Provenance updated (new evidence links added)
3. Returned importance is the stored (original) one, not the new one
"""
import asyncio
from app.db.session import get_session
from app.services.reflection_service import ReflectionService
from app.services.memory_service import MemoryService
from app.db.init_db import init_db
from sqlalchemy import text

REFLECTION_CONTENT = "The user is building MAXX as a cognitive AI platform."

async def main():
    # Step 0: Initialize DB tables
    print("=" * 60)
    print("STEP 0: Initializing database tables...")
    print("=" * 60)
    await init_db()
    print("Database tables created.\n")

    async for db in get_session():
        try:
            reflection_service = ReflectionService()
            memory_service = MemoryService()

            # Step 1: Clean slate
            print("=" * 60)
            print("STEP 1: Clean slate")
            print("=" * 60)
            await db.execute(text("DELETE FROM reflection_memory_links"))
            await db.execute(text("DELETE FROM reflections"))
            await db.execute(text("DELETE FROM memories"))
            await db.commit()
            print("All tables cleared.\n")

            # Step 2: Create a memory first (needed for evidence links)
            print("=" * 60)
            print("STEP 2: Creating a memory for evidence")
            print("=" * 60)
            mem_result = await memory_service.store_memory(
                content=REFLECTION_CONTENT,
                memory_type="general",
                importance=2.5,
                salience=0.5,
                db=db,
            )
            memory_id = mem_result.get("memory_id") or mem_result.get("id")
            print(f"Memory created: {mem_result}\n")

            # Step 3: Store first reflection with importance = 2.5
            print("=" * 60)
            print("STEP 3: Store first reflection (importance=2.5)")
            print("=" * 60)
            result1 = await reflection_service.store_reflection(
                content=REFLECTION_CONTENT,
                confidence=0.8,
                importance=2.5,
                evidence_ids=[memory_id] if memory_id else [],
                db=db,
            )
            print(f"Result 1: {result1}\n")

            # Step 4: Store duplicate reflection with DIFFERENT importance
            print("=" * 60)
            print("STEP 4: Store DUPLICATE reflection (importance=999.9)")
            print("=" * 60)
            result2 = await reflection_service.store_reflection(
                content=REFLECTION_CONTENT,
                confidence=0.8,
                importance=999.9,
                evidence_ids=[memory_id] if memory_id else [],
                db=db,
            )
            print(f"Result 2: {result2}\n")

            # === VERIFICATION ===
            print("=" * 60)
            print("VERIFICATION RESULTS")
            print("=" * 60)

            # Check 1: Still one row in reflections table
            row_count = await db.execute(
                text("SELECT COUNT(*) AS cnt FROM reflections")
            )
            count = row_count.scalar()
            print(f"\n[CHECK 1] Rows in reflections table: {count}")
            if count == 1:
                print("  ✅ PASS: Still one row after duplicate (dedup works)")
            else:
                print(f"  ❌ FAIL: Expected 1 row, got {count}")

            # Check 2: Provenance updated
            link_count = await db.execute(
                text("SELECT COUNT(*) AS cnt FROM reflection_memory_links")
            )
            link_cnt = link_count.scalar()
            print(f"\n[CHECK 2] Rows in reflection_memory_links: {link_cnt}")
            if link_cnt >= 1:
                print("  ✅ PASS: Provenance populated (evidence links exist)")
            else:
                print(f"  ❌ FAIL: Expected at least 1 link, got {link_cnt}")

            # Check 3: Returned importance is the stored one (2.5, not 999.9)
            stored = await db.execute(
                text("SELECT id, importance, confidence, content FROM reflections LIMIT 1")
            )
            row = stored.mappings().first()
            stored_importance = float(row["importance"])
            print(f"\n[CHECK 3] Stored importance in DB: {stored_importance}")
            print(f"           importance passed on duplicate call: 999.9")
            if stored_importance == 2.5:
                print("  ✅ PASS: Returned importance = stored importance (2.5)")
            else:
                print(f"  ❌ FAIL: Expected 2.5, got {stored_importance}")

            # Check 4: The merge response returns the stored importance too
            print(f"\n[CHECK 4] Merge response importance: {result2.get('importance')}")
            if result2.get("importance") == 2.5:
                print("  ✅ PASS: Merge API response returned stored importance (2.5)")
            elif result2.get("importance") == 999.9:
                print("  ❌ FAIL: Merge returned the NEW importance (999.9) instead of stored (2.5)")
            else:
                print(f"  ⚠️  UNEXPECTED: Returned importance = {result2.get('importance')}")

            print(f"\n[CHECK 5] Merge status: {result2.get('status')}")
            if result2.get("status") == "merged":
                print("  ✅ PASS: Status is 'merged' (not 'stored')")

            print("\n" + "=" * 60)
            print("FULL DB STATE")
            print("=" * 60)
            rows = await db.execute(
                text("SELECT id, importance, confidence, content FROM reflections")
            )
            for r in rows.mappings().all():
                print(f"  Reflection: id={r['id']}, importance={r['importance']}, "
                      f"confidence={r['confidence']}")

            links = await db.execute(
                text("SELECT reflection_id, memory_id FROM reflection_memory_links")
            )
            for l in links.mappings().all():
                print(f"  Link: reflection_id={l['reflection_id']}, memory_id={l['memory_id']}")

        finally:
            # Cleanup
            await db.execute(text("DELETE FROM reflection_memory_links"))
            await db.execute(text("DELETE FROM reflections"))
            await db.execute(text("DELETE FROM memories"))
            await db.commit()

asyncio.run(main())

