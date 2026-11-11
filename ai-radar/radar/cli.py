import argparse
import os
from pathlib import Path

import httpx

from radar.core import OpenAIProvider, deliver, run


def main() -> None:
    parser = argparse.ArgumentParser(description="Radar de notícias de IA")
    parser.add_argument("command", choices=["run", "alert"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        webhook = os.environ.get("DISCORD_WEBHOOK_URL") or None
        if args.command == "alert":
            deliver("Falha no serviço do radar de IA. Consulte o journal do systemd.", webhook, client)
        else:
            run(Path("sources.yaml"), Path("state/seen.json"), Path("out"), OpenAIProvider(), client, webhook, args.dry_run)
