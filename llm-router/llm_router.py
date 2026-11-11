import argparse
import os
import time
import tomllib
from pathlib import Path

import httpx
from pydantic import BaseModel


class Provider(BaseModel):
    name: str
    base_url: str
    model: str
    api_key_env: str


class Result(BaseModel):
    answer: str
    provider: str
    latency_seconds: float


class Router:
    def __init__(self, providers: list[Provider], client: httpx.Client | None = None):
        self.providers = providers
        self.client = client or httpx.Client(timeout=30)

    def route(self, prompt: str) -> Result:
        failures = []
        for provider in self.providers:
            started = time.monotonic()
            try:
                response = self.client.post(
                    f"{provider.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {os.environ[provider.api_key_env]}"},
                    json={"model": provider.model, "messages": [{"role": "user", "content": prompt}]},
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("empty content")
                return Result(answer=content, provider=provider.name,
                              latency_seconds=time.monotonic() - started)
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.TransportError,
                    ValueError, KeyError, IndexError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in (
                    429, *range(500, 600)
                ):
                    raise
                failures.append(f"{provider.name}: {exc}")
        raise RuntimeError("All providers failed: " + "; ".join(failures))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--config", default="providers.toml")
    parser.add_argument("--task", default="default")
    args = parser.parse_args()
    config = tomllib.loads(Path(args.config).read_text())
    providers = [Provider(**item) for item in config["tasks"][args.task]]
    result = Router(providers).route(args.prompt)
    print(f"{result.answer}\n\nProvider: {result.provider} ({result.latency_seconds:.2f}s)")


if __name__ == "__main__":
    main()
