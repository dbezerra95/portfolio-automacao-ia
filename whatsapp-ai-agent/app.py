import os
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field


class Message(BaseModel):
    sender: str = Field(min_length=1)
    text: str
    from_me: bool = False
    timestamp: datetime


class LLMProvider(Protocol):
    def reply(self, text: str) -> str: ...


class OpenAIProvider:
    def reply(self, text: str) -> str:
        response = httpx.post(
            f"{os.environ['LLM_BASE_URL'].rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
            json={"model": os.environ["LLM_MODEL"], "messages": [
                {"role": "system", "content": "Você atende clientes de uma loja de autopeças."},
                {"role": "user", "content": text},
            ]},
            timeout=30,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])


def classify(text: str) -> str:
    text = text.casefold()
    if any(word in text for word in ("spam", "cassino", "apostas")):
        return "spam"
    if any(word in text for word in ("fornecedor", "atacado", "distribuidora")):
        return "supplier"
    return "customer"


def create_app(db_path: str = "conversations.db", provider: LLMProvider | None = None) -> FastAPI:
    app = FastAPI()
    llm = provider or OpenAIProvider()
    @app.post("/webhook")
    def webhook(message: Message) -> dict[str, str | None]:
        now = datetime.now(UTC)
        with sqlite3.connect(db_path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS conversations "
                "(sender TEXT PRIMARY KEY, paused_until TEXT)"
            )
            if message.from_me:
                until = now + timedelta(hours=float(os.getenv("HUMAN_PAUSE_HOURS") or "12"))
                db.execute(
                    "INSERT INTO conversations VALUES (?, ?) ON CONFLICT(sender) "
                    "DO UPDATE SET paused_until=excluded.paused_until",
                    (message.sender, until.isoformat()),
                )
                return {"status": "human_handoff", "reply": None}
            row = db.execute(
                "SELECT paused_until FROM conversations WHERE sender = ?", (message.sender,)
            ).fetchone()
            if row and row[0] and datetime.fromisoformat(row[0]) > now:
                return {"status": "paused", "reply": None}
            category = classify(message.text)
            if category != "customer":
                return {"status": category, "reply": None}
            db.execute("INSERT OR IGNORE INTO conversations VALUES (?, NULL)", (message.sender,))
        return {"status": "customer", "reply": llm.reply(message.text)}

    return app


app = create_app(os.getenv("DATABASE_PATH") or "conversations.db")
