import argparse
import os
import re
import socket
import threading
import time
from decimal import Decimal
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from rpa_legacy.reconcile import make_report
from rpa_legacy.robot import collect


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Concilia contribuições fictícias")
    parser.add_argument("--competencia", required=True)
    parser.add_argument("--url", help="URL do sistema legado; sem esta opção inicia o demonstrador local")
    parser.add_argument("--folha", type=Path, default=Path("data/folha.xlsx"))
    parser.add_argument("--saida", type=Path, default=Path("output"))
    args = parser.parse_args()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", args.competencia):
        parser.error("competência deve ter formato AAAA-MM")
    username, password = os.getenv("LEGACY_USER"), os.getenv("LEGACY_PASSWORD")
    if not username or not password:
        parser.error("configure LEGACY_USER e LEGACY_PASSWORD no ambiente ou em .env")
    server = None
    thread = None
    url = args.url
    if not url:
        from rpa_legacy.app import app
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError("Local system failed to start")
            time.sleep(0.05)
        else:
            raise RuntimeError("Local system startup timed out")
    try:
        export = collect(url, username, password, args.competencia, args.saida)
        counts = make_report(export, args.folha, args.competencia, Decimal(os.getenv("RPA_TOLERANCE", "0.01")), args.saida / "conciliacao.xlsx")
        print("Resumo:", ", ".join(f"{k}: {v}" for k, v in counts.items()) or "nenhum registro")
        print(f"Relatório: {args.saida / 'conciliacao.xlsx'}")
    finally:
        if server and thread:
            server.should_exit = True
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
