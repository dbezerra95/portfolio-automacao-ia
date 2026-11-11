from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app
from app import classify, create_app


class FakeProvider:
    def reply(self, text: str) -> str:
        return "Resposta de teste"


def test_classification():
    assert classify("Olá") == "customer"
    assert classify("Sou fornecedor") == "supplier"
    assert classify("cassino online") == "spam"


def test_webhook_and_handoff(tmp_path):
    client = TestClient(create_app(str(tmp_path / "test.db"), FakeProvider()))
    payload = {
        "sender": "demo",
        "text": "Tem filtro?",
        "from_me": False,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    assert client.post("/webhook", json=payload).json()["reply"] == "Resposta de teste"
    assert (
        client.post("/webhook", json={**payload, "text": "Sou fornecedor"}).json()["status"]
        == "supplier"
    )
    assert client.post("/webhook", json={**payload, "text": "spam"}).json()["status"] == "spam"
    assert (
        client.post("/webhook", json={**payload, "from_me": True}).json()["status"]
        == "human_handoff"
    )
    assert client.post("/webhook", json=payload).json()["status"] == "paused"
    assert (
        client.post("/webhook", json={**payload, "sender": "outro"}).json()["status"] == "customer"
    )


@pytest.mark.parametrize(("configured_hours", "pause_hours"), [("", 12), ("2.5", 2.5)])
def test_pause_expires(tmp_path, monkeypatch, configured_hours, pause_hours):
    start = datetime(2026, 1, 1, tzinfo=UTC)

    class Clock(datetime):
        current = start

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(app, "datetime", Clock)
    monkeypatch.setenv("HUMAN_PAUSE_HOURS", configured_hours)
    provider = Mock()
    provider.reply.return_value = "Resposta"
    client = TestClient(create_app(str(tmp_path / "test.db"), provider))
    payload = {"sender": "demo", "text": "Tem filtro?", "timestamp": start.isoformat()}
    assert (
        client.post("/webhook", json={**payload, "from_me": True}).json()["status"]
        == "human_handoff"
    )
    Clock.current = start + timedelta(hours=pause_hours, seconds=-1)
    assert client.post("/webhook", json=payload).json() == {"status": "paused", "reply": None}
    provider.reply.assert_not_called()
    Clock.current = start + timedelta(hours=pause_hours)
    assert client.post("/webhook", json=payload).json() == {
        "status": "customer",
        "reply": "Resposta",
    }
    provider.reply.assert_called_once_with("Tem filtro?")


@pytest.mark.parametrize(("text", "status"), [("Sou fornecedor", "supplier"), ("spam", "spam")])
def test_ignored_messages_do_not_reply(tmp_path, text, status):
    provider = Mock()
    client = TestClient(create_app(str(tmp_path / "test.db"), provider))
    response = client.post(
        "/webhook",
        json={"sender": "demo", "text": text, "timestamp": datetime.now(UTC).isoformat()},
    )
    assert response.json() == {"status": status, "reply": None}
    provider.reply.assert_not_called()


@pytest.fixture(autouse=True)
def audit_path(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CPF 123.456.789-01", "CPF [CPF]"),
        ("CPF 12345678901", "CPF [CPF]"),
        ("CNPJ 12.345.678/0001-90", "CNPJ [CNPJ]"),
        ("CNPJ 12345678000190", "CNPJ [CNPJ]"),
        ("Ligue (11) 99999-1234", "Ligue [TELEFONE]"),
        ("Ligue +55 11 99999-1234", "Ligue [TELEFONE]"),
        ("Email nome@example.com", "Email [EMAIL]"),
        ("Celular: 11999991234", "Celular: [TELEFONE]"),
        ("Ligue 999991234", "Ligue [TELEFONE]"),
        ("Tem filtro?", "Tem filtro?"),
    ],
)
def test_mask_pii(text, expected):
    assert app.mask_pii(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("vocês vendem no atacado?", "customer"),
        ("quero comprar de uma distribuidora", "customer"),
        ("sou fornecedor", "supplier"),
        ("represento a fabricante", "supplier"),
        ("tabela de preços para revenda", "supplier"),
        ("cassino online", "spam"),
    ],
)
def test_classification_intent(text, expected):
    assert classify(text) == expected


def test_provider_receives_masked_text(tmp_path):
    provider = Mock()
    provider.reply.return_value = "Resposta"
    client = TestClient(create_app(str(tmp_path / "test.db"), provider))
    client.post(
        "/webhook",
        json={
            "sender": "11999991234",
            "text": "CPF 123.456.789-01 e a@exemplo.com",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    provider.reply.assert_called_once_with("CPF [CPF] e [EMAIL]")


def test_audit_records_each_action_without_pii(tmp_path):
    import hashlib
    import json

    client = TestClient(create_app(str(tmp_path / "test.db"), FakeProvider()))
    payload = {
        "sender": "11999991234",
        "text": "email privado@exemplo.com",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    for changes in ({}, {"text": "sou fornecedor"}, {"text": "spam"}, {"from_me": True}, {}):
        assert client.post("/webhook", json={**payload, **changes}).status_code == 200
    raw = (tmp_path / "audit.jsonl").read_text()
    entries = [json.loads(line) for line in raw.splitlines()]
    assert [entry["action"] for entry in entries] == [
        "replied",
        "routed",
        "silenced",
        "paused",
        "paused",
    ]
    assert [entry["classification"] for entry in entries] == [
        "customer",
        "supplier",
        "spam",
        "customer",
        "customer",
    ]
    assert all(
        entry["conversation_id"] == hashlib.sha256(payload["sender"].encode()).hexdigest()
        for entry in entries
    )
    assert entries[0]["provider"] == "FakeProvider"
    assert all(entry["provider"] is None for entry in entries[1:])
    assert all(
        entry["timestamp"] and entry["latency_ms"] >= 0 and entry["error"] is None
        for entry in entries
    )
    assert payload["sender"] not in raw and "privado@exemplo.com" not in raw


@pytest.mark.parametrize(
    "exception",
    [
        app.httpx.TimeoutException("private text"),
        app.httpx.HTTPStatusError(
            "private text",
            request=app.httpx.Request("GET", "https://example.com"),
            response=app.httpx.Response(500),
        ),
    ],
)
def test_provider_failure_has_fallback_and_audit(tmp_path, exception):
    import json

    provider = Mock()
    provider.reply.side_effect = exception
    client = TestClient(create_app(str(tmp_path / "test.db"), provider))
    response = client.post(
        "/webhook",
        json={"sender": "11999991234", "text": "Olá", "timestamp": datetime.now(UTC).isoformat()},
    )
    assert response.status_code == 200
    assert "um atendente vai responder em breve" in response.json()["reply"].lower()
    raw = (tmp_path / "audit.jsonl").read_text()
    assert json.loads(raw)["error"] == type(exception).__name__
    assert "private text" not in raw
