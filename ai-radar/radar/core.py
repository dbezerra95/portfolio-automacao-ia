import hashlib
import json
import os
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

import feedparser
import httpx
import yaml
from pydantic import BaseModel


class Source(BaseModel):
    category: str
    url: str


class Item(BaseModel):
    title: str
    url: str
    category: str
    description: str = ""


class Provider(Protocol):
    def summarize(self, item: Item) -> str: ...


class OpenAIProvider:
    def summarize(self, item: Item) -> str:
        key = os.environ.get("LLM_API_KEY")
        if not key:
            raise ValueError("LLM_API_KEY is required")
        response = httpx.post(
            os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": os.environ.get("LLM_MODEL", "gpt-4o-mini"), "messages": [
                {"role": "system", "content": "Resuma a notícia em português brasileiro em uma frase, sem inventar fatos."},
                {"role": "user", "content": f"{item.title}\n{item.description}"},
            ]}, timeout=30,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])


def deliver(content: str, webhook: str | None, client: httpx.Client) -> None:
    """Send text to Discord, or print it when no webhook is configured."""
    if not webhook:
        print(content)
        return
    # Discord limits each message to 2,000 characters.
    for start in range(0, len(content), 2000):
        response = client.post(webhook, json={"content": content[start:start + 2000]})
        response.raise_for_status()


def run(config: Path, state_path: Path, output: Path, provider: Provider, client: httpx.Client,
        webhook: str | None = None, dry_run: bool = False, today: date | None = None) -> Path | None:
    """Fetch, summarize and deliver unseen items, persisting state after delivery."""
    today = today or date.today()
    try:
        sources = [Source.model_validate(source) for source in yaml.safe_load(config.read_text(encoding="utf-8"))]
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        seen = {key: value for key, value in state.items() if date.fromisoformat(value) >= today - timedelta(days=30)}
        new: list[tuple[str, Item]] = []
        for source in sources:
            response = client.get(source.url)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            if feed.bozo and not feed.entries:
                raise ValueError(f"Invalid feed: {source.url}")
            for entry in feed.entries:
                url = entry.get("link", "")
                if not url:
                    continue
                key = hashlib.sha256(url.encode()).hexdigest()
                if key in seen:
                    continue
                seen[key] = today.isoformat()
                new.append((key, Item(title=entry.get("title", "Sem título"), url=url, category=source.category, description=entry.get("summary", ""))))
        if not new:
            if not dry_run:
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(json.dumps(seen, indent=2), encoding="utf-8")
            return None
        groups: dict[str, list[str]] = defaultdict(list)
        for _, item in new:
            groups[item.category].append(f"- [{item.title}]({item.url}): {provider.summarize(item)}")
        digest = f"# Radar de IA | {today.isoformat()}\n\n" + "\n\n".join(
            f"## {category}\n" + "\n".join(lines) for category, lines in groups.items()) + "\n"
        output.mkdir(parents=True, exist_ok=True)
        path = output / f"{today.isoformat()}.md"
        path.write_text(digest, encoding="utf-8")
        deliver(digest, None if dry_run else webhook, client)
        if not dry_run:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(seen, indent=2), encoding="utf-8")
        return path
    except Exception as exc:
        try:
            deliver(f"Falha no radar de IA: {type(exc).__name__}", None if dry_run else webhook, client)
        except Exception as alert_exc:
            print(f"Falha ao enviar alerta: {type(alert_exc).__name__}")
        raise
