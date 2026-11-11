import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from qualifier.api import app
from qualifier.core import Message, SAFE_HANDOFF, conversation_step, guard_output


class FakeProvider:
    def reply(self, system: str, question: str) -> str:
        return question


@pytest.mark.parametrize("text", ["você vai ganhar", "o valor dos honorários", "recomendo entrar com ação", "90% de chance", "chance de sucesso é 80%", "seu caso configura uma infração", "honorários serão R$ 1000"])
def test_guard(text):
    assert guard_output(text) == SAFE_HANDOFF


def test_guard_allows_safe_reply():
    reply = "Um advogado poderá avaliar as informações."
    assert guard_output(reply) == reply


def test_progression_and_handoff():
    history = []
    for value, expected in [("Ana", "company"), ("Empresa Exemplo", "debt_amount"), ("1000", "situation"), ("Cobrança", "channel")]:
        result = conversation_step(history, value, FakeProvider())
        assert result.next_field == expected
        history.extend([Message(role="user", content=value), Message(role="assistant", content=result.reply, field=expected)])
    result = conversation_step(history, "email", FakeProvider())
    assert result.qualified and result.handoff.name == "Ana"
    assert result.handoff.debt_amount == 1000


def test_invalid_amount():
    history = [Message(role="user", content="Ana"), Message(role="assistant", content="?", field="company"), Message(role="user", content="Exemplo"), Message(role="assistant", content="?", field="debt_amount")]
    assert conversation_step(history, "não sei", FakeProvider()).next_field == "debt_amount"


@pytest.mark.parametrize(("text", "amount"), [
    ("R$ 1.000", "1000"), ("50.000", "50000"), ("1.000,50", "1000.50"),
    ("1000", "1000"), ("1000,5", "1000.5"),
])
def test_brazilian_debt_amount(text, amount):
    history = [Message(role="assistant", content="?", field="debt_amount")]
    result = conversation_step(history, text, FakeProvider())
    assert result.lead.debt_amount == Decimal(amount)


def test_endpoint(monkeypatch):
    monkeypatch.setattr("qualifier.api.OpenAIProvider", FakeProvider)
    response = TestClient(app).post("/qualify", json={"message": "Ana"})
    assert response.status_code == 200
    assert response.json()["next_field"] == "company"
