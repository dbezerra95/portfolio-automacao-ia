import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from judicial_monitor.main import Config, DataJudConfigError, datajud_alias, fetch_datajud, request_json, run

FIXTURES = Path(__file__).parent / "fixtures"
NUMBER = "0000001-73.2024.8.07.0001"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def handler(request):
    if "_search" in request.url.path:
        assert request.headers["Authorization"] == "APIKey test-key"
        assert json.loads(request.content)["query"]["match"]["numeroProcesso"] == "00000017320248070001"
        return httpx.Response(200, json=fixture("datajud.json"))
    if "comunicacao" in request.url.path:
        return httpx.Response(200, json=fixture("djen.json"))
    if "movimentacoes" in request.url.path:
        return httpx.Response(200, json=fixture("movimentos.json"))
    return httpx.Response(200, json=fixture("processos.json"))


@pytest.fixture(autouse=True)
def datajud_key(monkeypatch):
    monkeypatch.setenv("DATAJUD_API_KEY", "test-key")


def config(tmp_path):
    return Config(processes=[NUMBER], state_file=tmp_path / "state.json", audit_file=tmp_path / "audit.jsonl", delay_seconds=0)


def test_new_then_seen_and_audit_has_no_number(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    cfg = config(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert run(cfg, client) == 0
        assert len(capsys.readouterr().out.splitlines()) == 4
        assert run(cfg, client) == 0
        assert capsys.readouterr().out == ""
    lines = cfg.audit_file.read_text().splitlines()
    assert NUMBER not in "\n".join(lines)
    assert NUMBER.replace("-", "").replace(".", "") not in "\n".join(lines)
    assert [json.loads(line)["new_items"] for line in lines] == [1, 1, 1, 1, 0, 0, 0, 0]


def test_retry_429(monkeypatch):
    calls = []
    monkeypatch.setattr("judicial_monitor.main.time.sleep", lambda _: None)
    def retry_handler(request):
        calls.append(request)
        return httpx.Response(429 if len(calls) == 1 else 200, json={"items": []})
    with httpx.Client(transport=httpx.MockTransport(retry_handler)) as client:
        assert request_json(client, "https://example.com", {}, 0) == {"items": []}
    assert len(calls) == 2


def test_invalid_cnj():
    with pytest.raises(ValidationError):
        Config(processes=["0000001-74.2024.8.07.0001"])


def test_failure_alert(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setattr("judicial_monitor.main.time.sleep", lambda _: None)
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(503))) as client:
        assert run(config(tmp_path), client) == 1
    assert "ALERTA" in capsys.readouterr().out
    assert not (tmp_path / "state.json").exists()


def test_dry_run_does_not_save_state(tmp_path, monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert run(config(tmp_path), client, dry_run=True) == 0
    assert not (tmp_path / "state.json").exists()


def test_datajud_parsing_and_aliases(tmp_path):
    assert datajud_alias(NUMBER) == "api_publica_tjdft"
    assert datajud_alias("0000001-00.2024.8.26.0001") == "api_publica_tjsp"
    with pytest.raises(DataJudConfigError, match="não mapeado"):
        datajud_alias("0000001-00.2024.8.99.0001")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_datajud(client, config(tmp_path), NUMBER)
    assert result[0]["classe"] == "Procedimento Comum Cível"
    assert result[0]["assuntos"] == ["Contratos", "Indenização"]
    assert result[0]["orgaoJulgador"] == "Vara Cível"
    assert result[0]["movimentos"][0]["nome"] == "Distribuição"


def test_datajud_missing_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DATAJUD_API_KEY")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DataJudConfigError, match="DATAJUD_API_KEY"):
            fetch_datajud(client, config(tmp_path), NUMBER)
        assert run(config(tmp_path), client) == 1
    assert "DATAJUD_API_KEY" in capsys.readouterr().err
