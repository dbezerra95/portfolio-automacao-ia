from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app import create_app


class FakeProvider:
    def reply(self, text: str) -> str:
        return "Olá! Informe o modelo do veículo para consultarmos a peça."


with TemporaryDirectory() as directory:
    client = TestClient(create_app(str(Path(directory) / "demo.db"), FakeProvider()))
    for text, from_me in [("Preciso de um filtro", False), ("Vou ajudar você!", True),
                          ("Obrigado", False)]:
        result = client.post("/webhook", json={"sender": "cliente-demo", "text": text,
                             "from_me": from_me, "timestamp": datetime.now(UTC).isoformat()})
        print(f"{'Humano' if from_me else 'Cliente'}: {text}")
        print(f"Resultado: {result.json()}")
