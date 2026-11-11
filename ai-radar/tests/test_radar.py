import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from radar.core import deliver, run


class FakeProvider:
    def summarize(self, item):
        return "Resumo de pesquisa."


def test_digest_dedup_and_webhook(tmp_path):
    config = tmp_path / "sources.yaml"
    config.write_text('- category: Pesquisa\n  url: https://example.com/feed\n')
    calls = []
    feed = (Path(__file__).parent / "fixtures/feed.xml").read_bytes()
    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=feed if request.method == "GET" else b"{}")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        args = (config, tmp_path / "state.json", tmp_path / "out", FakeProvider(), client)
        path = run(*args, webhook="https://example.com/hook", today=date(2026, 1, 1))
        assert "## Pesquisa" in path.read_text()
        assert "Resumo de pesquisa." in path.read_text()
        assert run(*args, webhook="https://example.com/hook", today=date(2026, 1, 2)) is None
    posts = [request for request in calls if request.method == "POST"]
    assert len(posts) == 1
    import json
    assert "Nova pesquisa" in json.loads(posts[0].content)["content"]


def test_failure_alert(tmp_path):
    config = tmp_path / "sources.yaml"
    config.write_text('- category: IA\n  url: https://example.com/feed\n')
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(503 if request.method == "GET" else 204)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            run(config, tmp_path / "state.json", tmp_path / "out", FakeProvider(), client, "https://example.com/hook")
    assert b"Falha no radar" in requests[-1].content


def test_no_webhook_prints(capsys):
    with httpx.Client() as client:
        deliver("hello", None, client)
    assert capsys.readouterr().out.strip() == "hello"


def test_retention_expires_after_30_days(tmp_path):
    today = date(2026, 2, 1)
    old_url = "https://example.com/old"
    recent_url = "https://example.com/recent"
    config = tmp_path / "sources.yaml"
    config.write_text('- category: IA\n  url: https://example.com/feed\n')
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        hashlib.sha256(old_url.encode()).hexdigest(): (today - timedelta(days=31)).isoformat(),
        hashlib.sha256(recent_url.encode()).hexdigest(): (today - timedelta(days=29)).isoformat(),
    }))
    feed = f'<rss version="2.0"><channel><title>Feed</title><link>https://example.com</link><description>Test</description><item><title>Old</title><link>{old_url}</link></item><item><title>Recent</title><link>{recent_url}</link></item></channel></rss>'
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=feed))) as client:
        path = run(config, state, tmp_path / "out", FakeProvider(), client, today=today)
    digest = path.read_text()
    assert old_url in digest
    assert recent_url not in digest
    saved = json.loads(state.read_text())
    assert saved[hashlib.sha256(old_url.encode()).hexdigest()] == today.isoformat()
    assert saved[hashlib.sha256(recent_url.encode()).hexdigest()] == (today - timedelta(days=29)).isoformat()
