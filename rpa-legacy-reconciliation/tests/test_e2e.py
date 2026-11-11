import json
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Error, sync_playwright
from rpa_legacy.app import app
from rpa_legacy.robot import collect


@pytest.fixture
def browser_available():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Error as exc:
            if not Path(p.chromium.executable_path).exists():
                pytest.skip("Playwright Chromium is not installed")
            raise exc
        browser.close()


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("LEGACY_USER", "demo")
    monkeypatch.setenv("LEGACY_PASSWORD", "test")
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
        time.sleep(.05)
    else:
        raise RuntimeError("Server did not start")
    yield url
    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.e2e
def test_robot_download(browser_available, server, tmp_path):
    result = collect(server, "demo", "test", "2026-10", tmp_path)
    assert len(result.read_text().splitlines()) == 6
    events = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert [e["step"] for e in events] == ["login", "consulta", "exportacao"]
    assert all(e["outcome"] == "success" for e in events)


@pytest.mark.e2e
def test_failure_screenshot_and_audit(browser_available, server, tmp_path):
    with pytest.raises(Exception):
        collect(server, "demo", "wrong", "2026-10", tmp_path, timeout_ms=200, attempts=1)
    assert (tmp_path / "falha.png").stat().st_size > 0
    event = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[-1])
    assert event["step"] == "login" and event["outcome"] == "failure"
    assert "wrong" not in (tmp_path / "audit.jsonl").read_text()
