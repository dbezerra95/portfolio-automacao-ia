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
    payload = {"sender": "demo", "text": "Tem filtro?", "from_me": False,
               "timestamp": datetime.now(UTC).isoformat()}
    assert client.post("/webhook", json=payload).json()["reply"] == "Resposta de teste"
    assert client.post("/webhook", json={**payload, "text": "Sou fornecedor"}).json()["status"] == "supplier"
    assert client.post("/webhook", json={**payload, "text": "spam"}).json()["status"] == "spam"
    assert client.post("/webhook", json={**payload, "from_me": True}).json()["status"] == "human_handoff"
    assert client.post("/webhook", json=payload).json()["status"] == "paused"
    assert client.post("/webhook", json={**payload, "sender": "outro"}).json()["status"] == "customer"


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
    assert client.post("/webhook", json={**payload, "from_me": True}).json()["status"] == "human_handoff"
    Clock.current = start + timedelta(hours=pause_hours, seconds=-1)
    assert client.post("/webhook", json=payload).json() == {"status": "paused", "reply": None}
    provider.reply.assert_not_called()
    Clock.current = start + timedelta(hours=pause_hours)
    assert client.post("/webhook", json=payload).json() == {"status": "customer", "reply": "Resposta"}
    provider.reply.assert_called_once_with("Tem filtro?")


@pytest.mark.parametrize(("text", "status"), [("Sou fornecedor", "supplier"), ("spam", "spam")])
def test_ignored_messages_do_not_reply(tmp_path, text, status):
    provider = Mock()
    client = TestClient(create_app(str(tmp_path / "test.db"), provider))
    response = client.post("/webhook", json={"sender": "demo", "text": text,
                                            "timestamp": datetime.now(UTC).isoformat()})
    assert response.json() == {"status": status, "reply": None}
    provider.reply.assert_not_called()
