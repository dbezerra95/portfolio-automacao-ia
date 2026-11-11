import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field, ValidationError, field_validator


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
    needs_handoff: bool = False


class Provider(Protocol):
    def reply(self, system: str, message: str) -> str: ...


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



class Extraction(Lead):
    @field_validator("name", "company", "situation", "channel", mode="before")
    @classmethod
    def validate_text(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Expected non-empty text")
        return value.strip()

    @field_validator("debt_amount", mode="before")
    @classmethod
    def parse_amount(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError("Invalid amount")
        try:
            raw = value.removeprefix("R$").strip().replace(".", "").replace(",", ".") if isinstance(value, str) else str(value)
            amount = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError("Invalid amount") from exc
        if not amount.is_finite() or amount < 0:
            raise ValueError("Invalid amount")
        return amount


INPUT_HANDOFF = FORBIDDEN + [
    r"\b(?:honorários|honorarios)\b",
    r"\b(?:quanto|qual|que)\s+(?:é\s+o\s+)?(?:custa|custo|preço|preco|valor)",
    r"\b(?:chances?|probabilidade)\b.*\b(?:ganhar|sucesso|perder)\b",
    r"\b(?:posso|devo)\s+(?:processar|ajuizar|entrar com|recorrer)",
    r"\b(?:opinião|opiniao|orientação|orientacao|conselho|parecer)\s+jurídic[oa]",
]


def conversation_step(history: list[Message], new_message: str, provider: Provider) -> Result:
    """Extract missing fields from each message and choose a fixed next question."""
    values: dict[str, object] = {}
    system = (Path(__file__).parent.parent / "prompts" / "system.md").read_text(encoding="utf-8")
    unsafe_output = False
    for message in [*history, Message(role="user", content=new_message)]:
        if message.role != "user" or not message.content.strip():
            continue
        missing = [field for field in QUESTIONS if field not in values]
        if not missing:
            break
        prompt = f"Campos ausentes: {', '.join(missing)}\nMensagem do lead: {message.content}"
        generated = provider.reply(system, prompt)
        if guard_output(generated) == SAFE_HANDOFF:
            unsafe_output = True
            continue
        try:
            data = json.loads(generated)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        for field in missing:
            if field not in data:
                continue
            try:
                value = getattr(Extraction.model_validate({field: data[field]}), field)
            except ValidationError:
                continue
            if field == "name" and value is not None:
                if not re.fullmatch(r"[^\W\d_]+(?:[ -][^\W\d_]+)*", value) or value.casefold() not in message.content.casefold():
                    continue
            if value is not None:
                values[field] = value
    lead = Lead(**values)
    missing_field = next((field for field in QUESTIONS if field not in values), None)
    input_handoff = any(re.search(pattern, new_message, re.IGNORECASE) for pattern in INPUT_HANDOFF)
    if input_handoff or unsafe_output:
        return Result(reply=SAFE_HANDOFF, lead=lead, qualified=False, next_field=missing_field, needs_handoff=True)
    if missing_field is None:
        return Result(reply="Obrigado. Encaminharemos as informações para um advogado.", lead=lead, qualified=True, handoff=lead)
    return Result(reply=QUESTIONS[missing_field], lead=lead, qualified=False, next_field=missing_field)
