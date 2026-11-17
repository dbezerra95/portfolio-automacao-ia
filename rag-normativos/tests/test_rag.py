import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from rag_normativos.api import app
from rag_normativos.core import (
    LLM_DOWN, NOT_FOUND, Index, answer, build_index, cited_articles, embed_texts, is_grounded, load_corpus, parse_norma, tokenize,
)

ROOT = Path(__file__).parent.parent
EVAL = [
    ("Qual a carência mínima de contribuições mensais para ser elegível a benefício programado?", "LC 108/2001", "Art. 3º"),
    ("Em quanto tempo prescreve o direito às prestações não pagas nem reclamadas?", "LC 109/2001", "Art. 75"),
    ("Quais institutos os planos de benefícios devem prever, como portabilidade e resgate?", "LC 109/2001", "Art. 14"),
    ("Quantos membros tem o conselho deliberativo e como é a composição paritária?", "LC 108/2001", "Art. 11"),
    ("Qual o mandato dos membros do conselho deliberativo?", "LC 108/2001", "Art. 12"),
    ("Quem equaciona o resultado deficitário dos planos das entidades fechadas?", "LC 109/2001", "Art. 21"),
    ("Para onde vai o resultado superavitário do plano ao final do exercício?", "LC 109/2001", "Art. 20"),
    ("Os administradores respondem civilmente pelos danos que causarem à entidade?", "LC 109/2001", "Art. 63"),
]


class FakeProvider:
    def __init__(self, text="O mandato é de quatro anos (Art. 12)."):
        self.text, self.calls = text, 0

    def reply(self, system, user):
        self.calls += 1
        return self.text


@pytest.fixture(scope="module")
def index():
    return Index(load_corpus(ROOT / "data"))


def test_corpus_chunks_one_article_each(index):
    keys = [(c.norma, c.artigo) for c in index.chunks]
    assert len(keys) == len(set(keys))
    assert {c.norma for c in index.chunks} == {"LC 108/2001", "LC 109/2001"}
    art14 = next(c for c in index.chunks if (c.norma, c.artigo) == ("LC 109/2001", "Art. 14"))
    assert "portabilidade" in art14.text and "Art. 15" not in art14.text


def test_vetoed_article_is_skipped(tmp_path):
    path = tmp_path / "lc999_2001.txt"
    path.write_text("Fonte: x\nArt. 1º Texto.\nParágrafo único. Mais.\nArt. 2º (VETADO)\nArt. 3º Outro.\n", encoding="utf-8")
    chunks = parse_norma(path)
    assert [c.artigo for c in chunks] == ["Art. 1º", "Art. 3º"]
    assert "Mais." in chunks[0].text


@pytest.mark.parametrize("question,norma,artigo", EVAL)
def test_retrieval_expected_article_in_top3(index, question, norma, artigo):
    top = [(c.norma, c.artigo) for c, _ in index.search(question, 3)]
    assert (norma, artigo) in top


def test_tokenize_drops_accents_stopwords_and_plural():
    assert tokenize("As contribuições dos participantes") == ["contribuicao", "participante"]


def test_answer_with_citation_is_grounded(index):
    provider = FakeProvider()
    result = answer("Qual o mandato dos membros do conselho deliberativo?", index, provider)
    assert result.grounded and provider.calls == 1
    assert [(c.norma, c.artigo) for c in result.citations] == [("LC 108/2001", "Art. 12")]
    assert "quatro anos" in result.citations[0].trecho


def test_below_threshold_refuses_without_calling_llm(index):
    provider = FakeProvider()
    result = answer("Qual a capital da França?", index, provider)
    assert result.answer == NOT_FOUND and not result.grounded and result.citations == []
    assert provider.calls == 0


def test_citation_outside_retrieved_is_not_grounded(index):
    result = answer("Qual o mandato dos membros do conselho deliberativo?", index, FakeProvider("Veja o Art. 70."))
    assert not result.grounded and result.citations == []


def test_wrong_norma_for_retrieved_number_is_not_grounded(index):
    text = "O mandato é de quatro anos (Art. 12 da LC 109/2001)."
    assert not answer("Qual o mandato dos membros do conselho deliberativo?", index, FakeProvider(text)).grounded


def test_answer_without_citation_is_not_grounded(index):
    result = answer("Qual o mandato dos membros do conselho deliberativo?", index, FakeProvider("Quatro anos."))
    assert not result.grounded


def test_cited_articles_parses_lists_and_norma():
    assert cited_articles("Arts. 14, 15 e 16 e o § 1º do art. 3º da LC 108") == [
        (None, "14"), (None, "15"), (None, "16"), ("108", "3")]


def test_llm_failure_degrades_to_not_grounded(index):
    class Down:
        def reply(self, system, user):
            raise httpx.ConnectError("refused")
    result = answer("Qual o mandato dos membros do conselho deliberativo?", index, Down())
    assert result.answer == LLM_DOWN and not result.grounded


def test_audit_log_records_question_articles_and_flag(index, tmp_path):
    log = tmp_path / "logs" / "audit.jsonl"
    answer("Qual o mandato dos membros do conselho deliberativo?", index, FakeProvider(), audit_path=log)
    answer("Qual a capital da França?", index, FakeProvider(), audit_path=log)
    first, second = [json.loads(line) for line in log.read_text().splitlines()]
    assert first["grounded"] and "LC 108/2001 Art. 12" in first["retrieved"]
    assert not second["grounded"] and second["retrieved"] == []


def test_embeddings_retrieval_with_mock_endpoint(monkeypatch):
    def handler(request):
        inputs = json.loads(request.content)["input"]
        return httpx.Response(200, json={"data": [{"embedding": [1.0, 0.0] if "mandato" in t else [0.0, 1.0]} for t in inputs]})
    real_post = httpx.post
    monkeypatch.setattr("rag_normativos.core.httpx.post", lambda url, **kw: httpx.Client(transport=httpx.MockTransport(handler)).post(url, **kw))
    vectors = embed_texts(["mandato", "outro"])
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    chunks = load_corpus(ROOT / "data")[:2]
    index = Index(chunks, [[1.0, 0.0], [0.0, 1.0]])
    hit = index.search("mandato", 1, embed_texts)[0]
    assert hit[0] == chunks[0] and hit[1] == pytest.approx(1.0)
    assert real_post is not None


def test_index_roundtrip(tmp_path):
    path = tmp_path / "chunks.json"
    build_index(ROOT / "data").save(path)
    assert len(Index.load(path).chunks) == len(load_corpus(ROOT / "data"))


def test_endpoint(monkeypatch):
    monkeypatch.setattr("rag_normativos.api.OpenAICompatible", FakeProvider)
    monkeypatch.setenv("AUDIT_LOG", str(Path("/dev/null")))
    monkeypatch.setenv("INDEX_PATH", str(ROOT / "missing.json"))
    monkeypatch.setenv("DATA_DIR", str(ROOT / "data"))
    client = TestClient(app)
    ok = client.post("/ask", json={"question": "Qual o mandato dos membros do conselho deliberativo?"}).json()
    assert ok["grounded"] and ok["citations"][0] == {
        "norma": "LC 108/2001", "artigo": "Art. 12", "trecho": ok["citations"][0]["trecho"]}
    refused = client.post("/ask", json={"question": "Qual a capital da França?"}).json()
    assert refused["grounded"] is False and refused["answer"] == NOT_FOUND


def test_n8n_workflow_nodes_and_connections():
    flow = json.loads((ROOT / "n8n/workflow.json").read_text())
    nodes = {n["name"]: n for n in flow["nodes"]}
    assert nodes["Webhook"]["type"] == "n8n-nodes-base.webhook" and nodes["Webhook"]["parameters"]["httpMethod"] == "POST"
    assert nodes["Ask"]["type"] == "n8n-nodes-base.httpRequest" and nodes["Ask"]["parameters"]["url"].endswith("/ask")
    assert nodes["Grounded?"]["type"] == "n8n-nodes-base.if"
    assert "$json.grounded" in json.dumps(nodes["Grounded?"]["parameters"])
    assert {nodes["Respond answer"]["type"], nodes["Respond forwarded"]["type"]} == {"n8n-nodes-base.respondToWebhook"}
    assert "encaminhada para a área responsável" in nodes["Respond forwarded"]["parameters"]["responseBody"]
    links = {name: [[t["node"] for t in branch] for branch in c["main"]] for name, c in flow["connections"].items()}
    assert links == {"Webhook": [["Ask"]], "Ask": [["Grounded?"]], "Grounded?": [["Respond answer"], ["Respond forwarded"]]}


@pytest.fixture
def lc108_chunks(index):
    return [c for c in index.chunks if c.norma == "LC 108/2001" and c.artigo in {"Art. 12", "Art. 17", "Art. 21"}]


@pytest.mark.parametrize("text", ["Arts. 12 a 70", "arts. 12 ao 70", "Arts. 12 até 70", "Arts. 12 - 70", "Arts. 12 – 70", "Arts. 12 a 21"])
def test_range_with_unretrieved_article_is_not_grounded(lc108_chunks, text):
    assert not is_grounded(text, lc108_chunks)


def test_range_fully_retrieved_is_grounded(index):
    chunks = [c for c in index.chunks if c.norma == "LC 108/2001" and c.artigo in {"Art. 10", "Art. 11", "Art. 12"}]
    assert is_grounded("Arts. 10 a 12", chunks)


@pytest.mark.parametrize("text", [
    "Art. 12 da Constituição", "artigo 12 do Decreto 70", "Art. 12 da CF", "Art. 12 da Lei 8.020",
    "Art. 12 da Resolução 1", "Art. 12 da Lei Complementar nº 70", "Art. 12 da LC nº 109", "Art. 12 da Lei 109",
])
def test_other_or_wrong_norma_is_not_grounded(lc108_chunks, text):
    assert not is_grounded(text, lc108_chunks)


@pytest.mark.parametrize("text", ["Art. 12 da LC nº 108", "Art. 12 da Lei Complementar 108/2001", "Art. 12 da LC 108/2001", "Art. 12 do Plano"])
def test_named_lc_matching_retrieved_is_grounded(lc108_chunks, text):
    assert is_grounded(text, lc108_chunks)


def test_citations_shown_respect_named_norma(index):
    chunks = [c for c in index.chunks if c.artigo == "Art. 14" and c.norma in {"LC 108/2001", "LC 109/2001"}]
    assert len(chunks) == 2

    class Both:
        mode = "bm25"
        def search(self, question, k=3, embed=None):
            return [(c, 1.0) for c in chunks]
    result = answer("x", Both(), FakeProvider("Veja o Art. 14 da LC 109/2001."), min_score=0)
    assert result.grounded and [(c.norma, c.artigo) for c in result.citations] == [("LC 109/2001", "Art. 14")]
