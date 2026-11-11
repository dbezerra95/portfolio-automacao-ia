import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class Lead(BaseModel):
    name: str | None = None
    company: str | None = None
    debt_amount: Decimal | None = Field(default=None, ge=0)
    situation: str | None = None
    channel: str | None = None


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    field: str | None = None


class Result(BaseModel):
    reply: str
    lead: Lead
    qualified: bool
    handoff: Lead | None = None
    next_field: str | None = None


class Provider(Protocol):
    def reply(self, system: str, question: str) -> str: ...


SAFE_HANDOFF = "Não posso orientar sobre questões jurídicas ou honorários. Um advogado poderá avaliar seu caso."
QUESTIONS = {
    "name": "Qual é o seu nome?",
    "company": "Qual é o nome da empresa?",
    "debt_amount": "Qual é o valor aproximado da dívida? Informe apenas o número.",
    "situation": "Pode descrever brevemente a situação?",
    "channel": "Por qual canal você prefere receber contato?",
}
FORBIDDEN = [
    r"você\s+vai\s+ganhar", r"(?:valor|preço|custo)\s+(?:dos?\s+)?honorários",
    r"recomendo\s+(?:que\s+)?(?:entrar|ajuizar|processar)",
    r"\d+(?:[,.]\d+)?\s*%\s*(?:de\s+)?(?:chance|sucesso|probabilidade)",
    r"(?:chance|probabilidade)\s+de\s+(?:sucesso|ganhar)[^\d]{0,20}\d+\s*%",
    r"(?:seu caso|sua situação)\s+(?:é|configura|constitui)",
    r"(?:honorários|taxa|custo)\s+(?:serão?|custam?|de)\s*(?:r\$|\d)",
]


def guard_output(reply: str) -> str:
    """Replace replies matching prohibited legal advice or fee patterns."""
    if any(re.search(pattern, reply, re.IGNORECASE) for pattern in FORBIDDEN):
        return SAFE_HANDOFF
    return reply


def conversation_step(history: list[Message], new_message: str, provider: Provider) -> Result:
    """Rebuild the lead from field-tagged questions and process one response."""
    values: dict[str, object] = {}
    pending = "name"
    for message in [*history, Message(role="user", content=new_message)]:
        if message.role == "assistant":
            if message.field in QUESTIONS:
                pending = message.field
            continue
        value = message.content.strip()
        if not value or pending in values:
            continue
        if pending == "debt_amount":
            try:
                amount = Decimal(value.removeprefix("R$").strip().replace(".", "").replace(",", "."))
                if not amount.is_finite() or amount < 0:
                    continue
                values[pending] = amount
            except InvalidOperation:
                continue
        else:
            values[pending] = value
        pending = next((field for field in QUESTIONS if field not in values), "")
    lead = Lead(**values)
    missing = next((field for field in QUESTIONS if field not in values), None)
    if missing is None:
        return Result(reply="Obrigado. Encaminharemos as informações para um advogado.", lead=lead, qualified=True, handoff=lead)
    system = (Path(__file__).parent.parent / "prompts" / "system.md").read_text(encoding="utf-8")
    generated = provider.reply(system, QUESTIONS[missing])
    safe = guard_output(generated)
    # The collection question is fixed: generated text cannot change what is requested.
    reply = safe if safe == SAFE_HANDOFF else QUESTIONS[missing]
    return Result(reply=reply, lead=lead, qualified=False, next_field=missing)
