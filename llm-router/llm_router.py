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


class ConfigError(Exception):
    pass


class Router:
    def __init__(self, providers: list[Provider], client: httpx.Client | None = None):
        self.providers = providers
        self.client = client or httpx.Client(timeout=30)

    def route(self, prompt: str) -> Result:
        keys = {}
        for provider in self.providers:
            key = os.environ.get(provider.api_key_env)
            if not key:
                raise ConfigError(f"Missing API key environment variable: {provider.api_key_env}")
            keys[provider.api_key_env] = key
        failures = []
        for provider in self.providers:
            started = time.monotonic()
            try:
                response = self.client.post(
                    f"{provider.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {keys[provider.api_key_env]}"},
                    json={"model": provider.model, "messages": [{"role": "user", "content": prompt}]},
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    failures.append(f"{provider.name}: empty content")
                    continue
                return Result(answer=content, provider=provider.name,
                              latency_seconds=time.monotonic() - started)
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.TransportError) as exc:
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
    tasks = config.get("tasks", {})
    if args.task not in tasks:
        raise ConfigError(f"Unknown task: {args.task}")
    providers = [Provider(**item) for item in tasks[args.task]]
    result = Router(providers).route(args.prompt)
    print(f"{result.answer}\n\nProvider: {result.provider} ({result.latency_seconds:.2f}s)")


if __name__ == "__main__":
    main()
