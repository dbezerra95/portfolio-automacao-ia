from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml
from pydantic import BaseModel, field_validator


class Config(BaseModel):
    processes: list[str]
    djen_url: str = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
    tjdft_1g_url: str = "https://pje-consultapublica-api.tjdft.jus.br"
    tjdft_2g_url: str = "https://pje2i-consultapublica-api.tjdft.jus.br"
    state_file: Path = Path("state.json")
    audit_file: Path = Path("audit.jsonl")
    delay_seconds: float = 1

    @field_validator("processes")
    @classmethod
    def validate_processes(cls, values: list[str]) -> list[str]:
        for value in values:
            if not re.fullmatch(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}", value):
                raise ValueError("Formato de número CNJ inválido")
            n = re.sub(r"\D", "", value)
            if int(n[:7] + n[9:] + n[7:9]) % 97 != 1:
                raise ValueError("Dígitos verificadores CNJ inválidos")
        return values

    @field_validator("delay_seconds")
    @classmethod
    def validate_delay(cls, value: float) -> float:
        if value < 0:
            raise ValueError("delay_seconds deve ser não negativo")
        return value


def mask(number: str) -> str:
    return "*******-**.****.*.**." + number[-4:]


def request_json(client: httpx.Client, url: str, params: dict[str, Any], delay: float) -> dict[str, Any]:
    for attempt in range(3):
        time.sleep(delay)
        response = client.get(url, params=params)
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Resposta da API não é um objeto JSON")
        return data
    raise RuntimeError("Tentativas esgotadas")


def fetch_djen(client: httpx.Client, config: Config, number: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        data = request_json(client, config.djen_url, {"numeroProcesso": re.sub(r"\D", "", number), "itensPorPagina": 100, "pagina": page}, config.delay_seconds)
        batch = data.get("items") or []
        items.extend(batch)
        if len(batch) < 100 or len(items) >= data.get("count", len(items)):
            return items
        page += 1


def fetch_movements(client: httpx.Client, config: Config, number: str, base: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 0
    while True:
        data = request_json(client, f"{base}/v1/processos", {"numeroProcesso": re.sub(r"\D", "", number), "page": page}, config.delay_seconds)
        for process in data.get("result") or []:
            if re.sub(r"\D", "", str(process.get("numeroProcesso", ""))) != re.sub(r"\D", "", number):
                continue
            process_id = process.get("idProcesso")
            if not process_id:
                raise ValueError("Processo sem identificador no PJe")
            movement_page = 0
            while True:
                movements = request_json(client, f"{base}/v1/processos/{process_id}/movimentacoes", {"page": movement_page}, config.delay_seconds)
                items.extend(m for m in movements.get("result") or [] if not m.get("movimentoExcluido"))
                movement_page += 1
                if movement_page >= (movements.get("pageInfo") or {}).get("last", 1):
                    break
        page += 1
        if page >= (data.get("pageInfo") or {}).get("last", 1):
            return items


def item_id(source: str, number: str, item: dict[str, Any]) -> str:
    if source == "DJEN":
        identifier = item.get("hash") or item.get("id")
        if not identifier:
            raise ValueError("Comunicação sem identificador")
        key = str(identifier)
    else:
        key = json.dumps([item.get("id"), item.get("movimento"), item.get("dataAtualizacao")], ensure_ascii=False)
        if not item.get("id") and not item.get("movimento"):
            raise ValueError("Movimentação sem identificador ou descrição")
    return hashlib.sha256(f"{source}:{number}:{key}".encode()).hexdigest()


def notify(message: str, client: httpx.Client, dry_run: bool = False) -> None:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook or dry_run:
        print(message)
    else:
        response = client.post(webhook, json={"content": message})
        response.raise_for_status()


def alert(client: httpx.Client, dry_run: bool = False) -> None:
    message = "ALERTA: falha no judicial-monitor. Consulte o log do serviço."
    try:
        notify(message, client, dry_run)
    except Exception:
        print(message, file=sys.stderr)


def run(config: Config, client: httpx.Client, dry_run: bool = False) -> int:
    run_id = str(uuid.uuid4())
    seen: set[str] = set()
    if config.state_file.exists():
        state = json.loads(config.state_file.read_text(encoding="utf-8"))
        if not isinstance(state, list) or not all(isinstance(x, str) for x in state):
            raise ValueError("Estado inválido")
        seen = set(state)
    failed = False
    for number in config.processes:
        for source, base in (("DJEN", ""), ("TJDFT 1g", config.tjdft_1g_url), ("TJDFT 2g", config.tjdft_2g_url)):
            started = time.monotonic()
            count = 0
            error = None
            try:
                items = fetch_djen(client, config, number) if source == "DJEN" else fetch_movements(client, config, number, base)
                for item in items:
                    identity = item_id(source, number, item)
                    if identity in seen:
                        continue
                    description = str(item.get("tipoComunicacao") or item.get("movimento") or "Comunicação")
                    date = str(item.get("data_disponibilizacao") or item.get("dataAtualizacao") or "")
                    notify(f"{mask(number)} | {source} | {description} | {date}", client, dry_run)
                    seen.add(identity)
                    count += 1
                    if not dry_run:
                        config.state_file.parent.mkdir(parents=True, exist_ok=True)
                        tmp = config.state_file.with_suffix(config.state_file.suffix + ".tmp")
                        tmp.write_text(json.dumps(sorted(seen)), encoding="utf-8")
                        tmp.replace(config.state_file)
            except Exception as exc:
                failed = True
                # Error classes avoid leaking URLs, process numbers, or webhook credentials.
                error = type(exc).__name__
            finally:
                config.audit_file.parent.mkdir(parents=True, exist_ok=True)
                with config.audit_file.open("a", encoding="utf-8") as log:
                    log.write(json.dumps({"run_id": run_id, "process_hash": hashlib.sha256(number.encode()).hexdigest(), "source": source, "new_items": count, "duration_seconds": round(time.monotonic() - started, 3), "error": error}) + "\n")
    if failed:
        alert(client, dry_run)
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("run")
    command.add_argument("--config", required=True)
    command.add_argument("--dry-run", action="store_true")
    sub.add_parser("alert")
    args = parser.parse_args()
    with httpx.Client(timeout=30, headers={"User-Agent": "judicial-monitor/0.1"}) as client:
        if args.command == "alert":
            alert(client)
            return 0
        try:
            config_path = Path(args.config).resolve()
            config = Config.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
            for field in ("state_file", "audit_file"):
                path = getattr(config, field)
                if not path.is_absolute():
                    setattr(config, field, config_path.parent / path)
            return run(config, client, args.dry_run)
        except Exception as exc:
            print(f"Falha na execução: {type(exc).__name__}", file=sys.stderr)
            alert(client, args.dry_run)
            return 1


if __name__ == "__main__":
    sys.exit(main())
