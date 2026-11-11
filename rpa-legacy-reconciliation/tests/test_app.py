from fastapi.testclient import TestClient
from rpa_legacy.app import app


def test_login_pagination_and_export(monkeypatch):
    monkeypatch.setenv("LEGACY_USER", "demo")
    monkeypatch.setenv("LEGACY_PASSWORD", "test")
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/contribuicoes").status_code == 303
        assert client.get("/exportar?competencia=2026-10").status_code == 303
        assert client.post("/login", data={"username": "demo", "password": "wrong"}).status_code == 401
        assert client.post("/login", data={"username": "demo", "password": "test"}).status_code == 303
        first = client.get("/contribuicoes?competencia=2026-10&pagina=1")
        second = client.get("/contribuicoes?competencia=2026-10&pagina=2")
        assert "P001" in first.text and "P003" not in first.text
        assert "P003" in second.text and "P001" not in second.text
        export = client.get("/exportar?competencia=2026-10")
        assert 'attachment' in export.headers['content-disposition']
        assert len(export.text.splitlines()) == 6
