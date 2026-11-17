from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.conversation_service import get_conversation_messages
from app.services.memory_service import MemoryService, _cosine_sim
from app.services.reflection_service import ReflectionService


class ContextService:
    def __init__(self):
        self.memory_service = MemoryService()
        self.reflection_service = ReflectionService()

    async def get_relevant_context(
        self,
        db: AsyncSession,
        query: str,
        memory_limit: int = 20,
        intent: str = "general",
    ):
        latest_user_message = query

        intent_config = {
            "goals": {
                "threshold": settings.SIMILARITY_THRESHOLD_GOALS,
                "memory_types": ["goal"],
                "mmr_limit": settings.MMR_LIMIT_GOALS,
            },
            "preferences": {
                "threshold": settings.SIMILARITY_THRESHOLD_PREFERENCES,
                "memory_types": ["preference"],
                "mmr_limit": settings.MMR_LIMIT_PREFERENCES,
            },
            "self_summary": {
                "threshold": settings.SIMILARITY_THRESHOLD_SELF_SUMMARY,
                "memory_types": ["preference", "fact", "goal", "project"],
                "mmr_limit": settings.MMR_LIMIT_SELF_SUMMARY,
            },
            "project": {
                "threshold": settings.SIMILARITY_THRESHOLD_PROJECTS,
                "memory_types": ["project"],
                "mmr_limit": settings.MMR_LIMIT_PROJECTS,
            },
            "general": {
                "threshold": settings.SIMILARITY_THRESHOLD_GENERAL,
                "memory_types": None,
                "mmr_limit": settings.MMR_LIMIT_GENERAL,
            },
        }

        config = intent_config.get(intent, intent_config["general"])
        threshold = config["threshold"]
        memory_types = config["memory_types"]
        mmr_limit = config["mmr_limit"]

        # Memory retrieval (skip MMR — will do global MMR later)
        memory_candidates, debug_memories = await self.memory_service.search_memories(
            query=latest_user_message,
            db=db,
            limit=memory_limit,
            similarity_threshold=threshold,
            memory_types=memory_types,
            mmr_limit=mmr_limit,
            skip_mmr=True,
        )

        # Normalise memory candidates for unified pipeline
        for item in memory_candidates:
            item["object_type"] = "memory"

        # Reflection retrieval — use lower threshold than memory
        # because reflection embeddings are further from any given query
        # (reflections are synthesized abstractions, not raw memories)
        reflection_threshold = max(threshold * 0.6, 0.35)
        reflection_candidates, debug_reflections = (
            await self.reflection_service.search_reflections(
                query=latest_user_message,
                db=db,
                limit=memory_limit,
                similarity_threshold=reflection_threshold,
            )
        )

        # Merge candidate pools
        merged_pool = memory_candidates + reflection_candidates

        # Global sort
        merged_pool.sort(
            key=lambda x: x["retrieval_score"],
            reverse=True,
        )

        # Global MMR
        selected_candidates = self._apply_mmr(
            merged_pool, settings.MMR_LAMBDA, mmr_limit
        )

        # Build final context
        final_context = []
        for item in selected_candidates:
            if item["object_type"] == "memory":
                final_context.append(item["memory"].content)
            elif item["object_type"] == "reflection":
                final_context.append(item["reflection"].content)

        # Combine debug info
        combined_debug_info = debug_memories + debug_reflections

        return final_context, combined_debug_info

    def _apply_mmr(self, candidates, mmr_lambda, mmr_limit):
        """Applies Maximal Marginal Relevance (MMR) to a list of candidates."""
        selected = []
        while candidates and len(selected) < mmr_limit:
            best = max(
                candidates,
                key=lambda item: (
                    mmr_lambda * item["retrieval_score"]
                    - (1 - mmr_lambda) * max(
                        (
                            _cosine_sim(item["parsed_embedding"], s["parsed_embedding"])
                            for s in selected
                        ),
                        default=0.0,
                    )
                ),
            )
            selected.append(best)
            candidates.remove(best)
        return selected

    async def build_context(
        self,
        db: AsyncSession,
        query: str,
        conversation_id: int | None = None,
        memory_limit: int = 20,
        intent: str = "general",
    ):
        conversation_messages = []
        if conversation_id is not None:
            conversation_messages = await get_conversation_messages(
                db=db,
                conversation_id=conversation_id,
            )

        relevant_context_content, debug_info = await self.get_relevant_context(
            db=db,
            query=query,
            memory_limit=memory_limit,
            intent=intent,
        )

        return (
            relevant_context_content,
            debug_info,
            conversation_messages,
        )