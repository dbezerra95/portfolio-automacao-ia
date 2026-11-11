import httpx
import pytest

from llm_router import Provider, Router


@pytest.fixture
def providers(monkeypatch):
    monkeypatch.setenv("KEY", "test")
    return [Provider(name=name, base_url=f"https://{name}.example/v1", model="test",
                     api_key_env="KEY") for name in ("one", "two")]


def test_first_succeeds(providers):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"choices": [{"message": {"content": "ok"}}]})))
    result = Router(providers, client).route("hello")
    assert result.answer == "ok" and result.provider == "one" and result.latency_seconds >= 0


@pytest.mark.parametrize("first", [httpx.Response(429), httpx.Response(
    200, json={"choices": [{"message": {"content": ""}}]})])
def test_fallback(providers, first):
    def handler(request):
        if request.url.host == "one.example":
            return first
        return httpx.Response(200, json={"choices": [{"message": {"content": "second"}}]})
    result = Router(providers, httpx.Client(transport=httpx.MockTransport(handler))).route("hello")
    assert result.answer == "second" and result.provider == "two"


def test_all_fail(providers):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    with pytest.raises(RuntimeError, match="All providers failed"):
        Router(providers, client).route("hello")
