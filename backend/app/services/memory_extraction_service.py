from app.services.llm_service import generate_json_response


class MemoryExtractionService:

    async def extract_memories(self, message: str) -> list[dict]:

        prompt = f"""
You are MAXX's memory formation system.

Extract ONLY information worth storing as long-term memory.

Ignore:
- greetings
- acknowledgements
- small talk
- filler conversation
- temporary statements

Return JSON ONLY.

Write memories as complete factual statements optimized for retrieval and reasoning.

Always write memories in third person using "User".

Good:
- User prefers concise technical explanations.
- User is building MAXX as a cognitive AI platform.
- User's goal is to create an AI with long-term memory.

Bad:
- You prefer concise technical explanations.
- building MAXX
- create AI with memory

Schema:

[
  {{
    "content": "memory text",
    "memory_type": "project | preference | fact | goal | general",
    "salience": 0.0
  }}
]

Salience Guide:

0.0 - irrelevant
0.3 - weak
0.5 - useful
0.7 - important
0.9 - highly important

User Message:

{message}
"""

        messages = [
            {
                "role": "system",
                "content": "You extract long-term memories."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]

        try:
            result = await generate_json_response(messages)

            print("\n===== MEMORY EXTRACTION =====")
            print(result)
            print("============================\n")

            if isinstance(result, list):
                return result

            return []

        except Exception as e:
            print(f"Memory extraction error: {e}")
            return []
