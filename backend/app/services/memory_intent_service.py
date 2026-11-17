class MemoryIntentService:

    def detect_intent(self, query: str) -> str:

        q = query.lower()

        if any(x in q for x in [
            "what are my goals",
            "my goals",
            "goal"
        ]):
            return "goals"

        if any(x in q for x in [
            "what are my preferences",
            "my preferences",
            "preference"
        ]):
            return "preferences"

        if any(x in q for x in [
            "what do you know about me",
            "tell me about me",
            "summarize me",
            "who am i"
        ]):
            return "self_summary"

        if any(x in q for x in [
            "tell me about maxx",
            "what is maxx",
            "maxx"
        ]):
            return "project"

        return "general"
