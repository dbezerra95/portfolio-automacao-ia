import hashlib
import json
import os
import re
import sqlite3
import time
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
            json={
                "model": os.environ["LLM_MODEL"],
                "messages": [
                    {"role": "system", "content": "Você atende clientes de uma loja de autopeças."},
                    {"role": "user", "content": text},
                ],
            },
            timeout=30,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])


def mask_pii(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", "[EMAIL]", text)
    text = re.sub(
        r"\b(telefone|celular|fone|whatsapp)(\s*[:=]?\s*)(\d{10,11})(?!\d)",
        r"\1\2[TELEFONE]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?<!\d)(?:\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{14})(?!\d)", "[CNPJ]", text)
    text = re.sub(r"(?<!\d)(?:\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})(?!\d)", "[CPF]", text)
    return re.sub(
        r"(?<!\w)(?:\+55[ .-]?)?(?:\(\d{2}\)[ .-]?|\d{2}[ .-])?"
        r"\d{4,5}[ .-]\d{4}(?!\d)|(?<!\d)(?:55\d{10,11}|\d{8,10})(?!\d)",
        "[TELEFONE]",
        text,
    )


def classify(text: str) -> str:
    text = text.casefold()
    if any(word in text for word in ("spam", "cassino", "apostas")):
        return "spam"
    if re.search(
        r"\b(?:sou fornecedor(?:a)?|somos fornecedores|represento (?:a|o|uma|um)|"
        r"tabela de preços para revenda)\b",
        text,
    ):
        return "supplier"
    return "customer"


def create_app(db_path: str = "conversations.db", provider: LLMProvider | None = None) -> FastAPI:
    app = FastAPI()
    llm = provider or OpenAIProvider()

    @app.post("/webhook")
    def webhook(message: Message) -> dict[str, str | None]:
        started = time.monotonic()
        now = datetime.now(UTC)
        category = classify(message.text)
        action = "paused"
        provider_used = None
        error = None
        try:
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
                if category != "customer":
                    action = "routed" if category == "supplier" else "silenced"
                    return {"status": category, "reply": None}
                db.execute(
                    "INSERT OR IGNORE INTO conversations VALUES (?, NULL)", (message.sender,)
                )
            action = "replied"
            provider_used = type(llm).__name__
            try:
                reply = llm.reply(mask_pii(message.text))
            except (httpx.HTTPError, TimeoutError) as exc:
                error = type(exc).__name__
                reply = "Um atendente vai responder em breve."
            return {"status": "customer", "reply": reply}
        except Exception as exc:
            error = type(exc).__name__
            raise
        finally:
            entry = {
                "timestamp": now.isoformat(),
                "conversation_id": hashlib.sha256(message.sender.encode()).hexdigest(),
                "classification": category,
                "action": action,
                "provider": provider_used,
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "error": error,
            }
            with open(os.getenv("AUDIT_LOG_PATH") or "audit.jsonl", "a", encoding="utf-8") as log:
                log.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return app


app = create_app(os.getenv("DATABASE_PATH") or "conversations.db")
