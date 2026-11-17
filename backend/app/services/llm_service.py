import httpx
import json
import re


OLLAMA_URL = "http://localhost:11434/api/chat"

MODEL_NAME = "qwen2.5-coder:14b"


async def generate_response(messages):
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
    }

    timeout = httpx.Timeout(
        connect=30.0,
        read=300.0,
        write=30.0,
        pool=30.0
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            OLLAMA_URL,
            json=payload,
        )

    print("\n===== EXTRACTION STATUS =====")
    print(response.status_code)
    print("===== EXTRACTION BODY =====")
    print(response.text)
    print("===========================\n")

    response.raise_for_status()

    data = response.json()

    return data["message"]["content"]


async def generate_json_response(messages):
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
    }

    timeout = httpx.Timeout(
        connect=30.0,
        read=300.0,
        write=30.0,
        pool=30.0
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            OLLAMA_URL,
            json=payload,
        )

    response.raise_for_status()

    data = response.json()

    content = data["message"]["content"]

    print("\n===== RAW EXTRACTION RESPONSE =====")
    print(content)
    print("==================================\n")

    # Try to extract a JSON array from the assistant content using a regex
    match = re.search(r"\[[\s\S]*\]", content)

    if not match:
        return []

    return json.loads(match.group())