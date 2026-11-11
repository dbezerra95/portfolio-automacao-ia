import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from qualifier.api import app
from qualifier.core import Message, QUESTIONS, SAFE_HANDOFF, conversation_step, guard_output


class FakeProvider:
    def reply(self, system: str, message: str) -> str:
        text = message.split("Mensagem do lead: ", 1)[1]
        responses = {
            "Sou Ana Souza, da Oficina Horizonte. Tenho uma dívida de R$ 50.000 por uma cobrança indevida.": {
                "name": "Ana Souza", "company": "Oficina Horizonte", "debt_amount": "R$ 50.000", "situation": "cobrança indevida"
            },
            "E-mail": {"channel": "E-mail"}, "Oi, quanto custa?": {}, "Ana": {"name": "Ana"},
        }
        return json.dumps(responses.get(text, {}), ensure_ascii=False)


@pytest.mark.parametrize("text", ["você vai ganhar", "o valor dos honorários", "recomendo entrar com ação", "90% de chance", "chance de sucesso é 80%", "seu caso configura uma infração", "honorários serão R$ 1000"])
def test_guard(text):
    assert guard_output(text) == SAFE_HANDOFF


def test_extraction_and_handoff():
    text = "Sou Ana Souza, da Oficina Horizonte. Tenho uma dívida de R$ 50.000 por uma cobrança indevida."
    result = conversation_step([], text, FakeProvider())
    assert result.next_field == "channel" and result.reply == QUESTIONS["channel"]
    assert result.lead.name == "Ana Souza" and result.lead.company == "Oficina Horizonte"
    assert result.lead.debt_amount == Decimal("50000") and result.lead.situation == "cobrança indevida"
    history = [Message(role="user", content=text), Message(role="assistant", content=result.reply, field=result.next_field)]
    result = conversation_step(history, "E-mail", FakeProvider())
    assert result.qualified and result.handoff.channel == "E-mail"


def test_greeting_and_fee_question():
    result = conversation_step([], "Oi, quanto custa?", FakeProvider())
    assert result.lead.name is None and result.reply == SAFE_HANDOFF and result.needs_handoff
    assert result.next_field == "name"


def test_invalid_json_and_fields():
    class InvalidProvider:
        def reply(self, system: str, message: str) -> str:
            return "not JSON"
    assert conversation_step([], "Olá", InvalidProvider()).next_field == "name"

    class PartialProvider:
        def reply(self, system: str, message: str) -> str:
            return '{"name": "Ana", "debt_amount": "inválido", "company": 123}'
    lead = conversation_step([], "Ana", PartialProvider()).lead
    assert lead.name == "Ana" and lead.company is None and lead.debt_amount is None


@pytest.mark.parametrize(("text", "amount"), [
    ("R$ 1.000", "1000"), ("50.000", "50000"), ("1.000,50", "1000.50"),
    ("1000", "1000"), ("1000,5", "1000.5"),
])
def test_brazilian_debt_amount(text, amount):
    class AmountProvider:
        def reply(self, system: str, message: str) -> str:
            return json.dumps({"debt_amount": text})
    assert conversation_step([], text, AmountProvider()).lead.debt_amount == Decimal(amount)


def test_model_output_guard():
    class UnsafeProvider:
        def reply(self, system: str, message: str) -> str:
            return "Você vai ganhar"
    result = conversation_step([], "Olá", UnsafeProvider())
    assert result.reply == SAFE_HANDOFF and result.needs_handoff


def test_endpoint(monkeypatch):
    monkeypatch.setattr("qualifier.api.OpenAIProvider", FakeProvider)
    response = TestClient(app).post("/qualify", json={"message": "Ana"})
    assert response.status_code == 200 and response.json()["next_field"] == "company"
