import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from qualifier.core import Message, Result, conversation_step


class OpenAIProvider:
    def reply(self, system: str, message: str) -> str:
        key = os.environ.get("LLM_API_KEY")
        if not key:
            raise ValueError("LLM_API_KEY is required")
        response = httpx.post(
            os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": os.environ.get("LLM_MODEL", "gpt-4o-mini"), "messages": [
                {"role": "system", "content": system}, {"role": "user", "content": message}
            ]}, timeout=30,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])


class Request(BaseModel):
    history: list[Message] = []
    message: str


app = FastAPI()


@app.post("/qualify", response_model=Result)
def qualify(request: Request) -> Result:
    try:
        return conversation_step(request.history, request.message, OpenAIProvider())
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        raise HTTPException(status_code=502, detail="Qualifying provider unavailable") from exc
