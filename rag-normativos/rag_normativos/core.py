import json
import math
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Callable, Protocol

import httpx
from pydantic import BaseModel

NOT_FOUND = "Não encontrei isso nos normativos indexados."
LLM_DOWN = "Não consegui gerar a resposta agora (modelo indisponível). A pergunta deve seguir para a área responsável."
DEFAULT_MIN_SCORE = {"bm25": 0.18, "embeddings": 0.55}
STOPWORDS = set(
    "a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sob sobre e ou que se "
    "ao aos como qual quais quem quando onde ser sao foi sera esta esse essa isso este isto ha mais "
    "pode podem deve devem tem seu sua seus suas entre ate ja nao".split()
)
SYSTEM_PROMPT = (
    "Você responde perguntas sobre normas de previdência complementar. Responda em português, "
    "somente com base nos trechos fornecidos, e cite o artigo de onde saiu cada afirmação no formato "
    "'Art. N'. Se os trechos não bastarem, diga que não encontrou. Não use conhecimento externo."
)
ARTICLE = re.compile(r"^Art\. (\d+)(º)?(-[A-Z])?\.?\s")
ARTICLE_NUMBER = r"\d+º?(?:-[A-Z])?"
CITATION = re.compile(
    rf"\b[Aa]rt(?:igo)?s?\.?\s*(?P<numbers>{ARTICLE_NUMBER}(?:\s*(?:,|e|ou|ao|até|a|-|–)\s*{ARTICLE_NUMBER})*)"
    r"(?:,?\s+(?:da|do|de)\s+(?:"
    r"(?:LC|Lei Complementar)(?:\s+n[ºo.]*)?\s*(?P<lc>\d{3})(?!\d)"
    r"|Lei(?:\s+n[ºo.]*)?\s*(?P<lei>\d[\d.]*)"
    r"|(?P<other>Constitui\w+|CF\b|Decreto\w*|Resolu\w+|Portaria|Instru\w+|Emenda|Lei\b|LC\b|Medida|MP\b|C[óo]digo|Regulamento|Estatuto)"
    r"))?",
    re.IGNORECASE,
)
RANGE_WORDS = {"a", "ao", "até", "-", "–"}


class Chunk(BaseModel):
    norma: str
    artigo: str
    text: str


class Citation(BaseModel):
    norma: str
    artigo: str
    trecho: str


class Answer(BaseModel):
    answer: str
    citations: list[Citation]
    grounded: bool


class Provider(Protocol):
    def reply(self, system: str, user: str) -> str: ...


class OpenAICompatible:
    def reply(self, system: str, user: str) -> str:
        key = os.environ.get("LLM_API_KEY")
        response = httpx.post(
            os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            json={"model": os.environ.get("LLM_MODEL", "llama3.1"), "temperature": 0, "messages": [
                {"role": "system", "content": system}, {"role": "user", "content": user},
            ]}, timeout=120,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])


def embed_texts(texts: list[str]) -> list[list[float]]:
    base = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    key = os.environ.get("LLM_API_KEY")
    vectors: list[list[float]] = []
    for start in range(0, len(texts), 32):
        response = httpx.post(
            base + "/embeddings",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            json={"model": os.environ.get("EMBED_MODEL", "nomic-embed-text"), "input": texts[start:start + 32]},
            timeout=120,
        )
        response.raise_for_status()
        vectors += [item["embedding"] for item in response.json()["data"]]
    return vectors


def tokenize(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    tokens = []
    for word in re.findall(r"[a-z0-9]+", plain):
        if word in STOPWORDS:
            continue
        word = re.sub(r"coes$", "cao", word)
        tokens.append(word[:-1] if len(word) > 3 and word.endswith("s") else word)
    return tokens


def parse_norma(path: Path) -> list[Chunk]:
    """One chunk per article, with its paragraphs and items. Revoked or vetoed articles are skipped."""
    match = re.fullmatch(r"lc(\d+)_(\d{4})", path.stem)
    if not match:
        raise ValueError(f"Unexpected corpus file name: {path.name}")
    norma = f"LC {match[1]}/{match[2]}"
    blocks: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if ARTICLE.match(line + " "):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
    chunks = []
    for lines in blocks:
        head = ARTICLE.match(lines[0] + " ")
        body = lines[0][head.end():].strip()
        if body.strip("() ").upper() in {"VETADO", "REVOGADO"}:
            continue
        artigo = f"Art. {head[1]}{head[2] or ''}{head[3] or ''}"
        chunks.append(Chunk(norma=norma, artigo=artigo, text="\n".join(lines)))
    return chunks


def load_corpus(data_dir: Path) -> list[Chunk]:
    return [chunk for path in sorted(data_dir.glob("lc*.txt")) for chunk in parse_norma(path)]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.docs, self.k1, self.b = [Counter(doc) for doc in docs], k1, b
        self.lengths = [len(doc) for doc in docs]
        self.avg = sum(self.lengths) / len(docs)
        frequency = Counter(term for doc in self.docs for term in doc)
        n = len(docs)
        self.idf = {term: math.log(1 + (n - df + 0.5) / (df + 0.5)) for term, df in frequency.items()}

    def scores(self, query: list[str]) -> list[float]:
        """BM25 scores divided by the best score a chunk could reach for this query (unknown terms count in full)."""
        unknown = math.log(1 + (len(self.docs) + 0.5) / 0.5)
        ceiling = sum(self.idf.get(term, unknown) * (self.k1 + 1) for term in set(query))
        result = []
        for doc, length in zip(self.docs, self.lengths):
            score = 0.0
            for term in set(query):
                tf = doc.get(term, 0)
                if tf:
                    score += self.idf[term] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self.avg))
            result.append(score / ceiling if ceiling else 0.0)
        return result


def cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0


class Index:
    def __init__(self, chunks: list[Chunk], vectors: list[list[float]] | None = None) -> None:
        self.chunks, self.vectors = chunks, vectors
        self.bm25 = BM25([tokenize(chunk.text) for chunk in chunks])

    @property
    def mode(self) -> str:
        return "embeddings" if self.vectors else "bm25"

    def search(self, question: str, k: int = 3, embed: Callable[[list[str]], list[list[float]]] | None = None) -> list[tuple[Chunk, float]]:
        if embed and self.vectors:
            query = embed([question])[0]
            scores = [cosine(query, vector) for vector in self.vectors]
        else:
            scores = self.bm25.scores(tokenize(question))
        ranked = sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:k]
        return [(self.chunks[i], scores[i]) for i in ranked]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"chunks": [c.model_dump() for c in self.chunks], "vectors": self.vectors}, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Index":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls([Chunk(**c) for c in data["chunks"]], data["vectors"])


def build_index(data_dir: Path, embeddings: bool = False) -> Index:
    chunks = load_corpus(data_dir)
    return Index(chunks, embed_texts([c.text for c in chunks]) if embeddings else None)


def load_index() -> Index:
    """Load the saved index, or build a BM25 one from the corpus when `index` has not been run."""
    path = Path(os.environ.get("INDEX_PATH", "index/chunks.json"))
    return Index.load(path) if path.exists() else Index(load_corpus(Path(os.environ.get("DATA_DIR", "data"))))


def ask(question: str, index: Index, provider: Provider) -> Answer:
    """Answer with the settings from the environment (MIN_SCORE, AUDIT_LOG) and the index's retriever."""
    min_score = os.environ.get("MIN_SCORE")
    return answer(
        question, index, provider, float(min_score) if min_score else None,
        embed=embed_texts if index.vectors else None,
        audit_path=Path(os.environ.get("AUDIT_LOG", "logs/audit.jsonl")),
    )


def cited_articles(text: str) -> list[tuple[str | None, str]]:
    """Return (norma, article number) for every article in the answer, with ranges expanded.

    norma is None when the answer does not name one, "108"/"109" for those LCs, and any other
    string ("?" for Constituição, Decreto etc.) for a norma that is not in the corpus.
    """
    found = []
    for match in CITATION.finditer(text):
        norma = match["lc"] or (match["lei"].replace(".", "") if match["lei"] else None) or ("?" if match["other"] else None)
        tokens = re.findall(rf"{ARTICLE_NUMBER}|ao|até|a|–|-|,|e|ou", match["numbers"], flags=re.IGNORECASE)
        numbers: list[str] = []
        range_pending = False
        for token in tokens:
            if token.lower() in RANGE_WORDS:
                range_pending = True
            elif token[0].isdigit():
                number = token.replace("º", "")
                if range_pending and numbers[-1].isdigit() and number.isdigit() and 0 < int(number) - int(numbers[-1]) < 500:
                    numbers += [str(n) for n in range(int(numbers[-1]) + 1, int(number))]
                numbers.append(number)
                range_pending = False
        found += [(norma, number) for number in numbers]
    return found


def _key(chunk: Chunk) -> tuple[str, str]:
    return chunk.norma.split()[1].split("/")[0], chunk.artigo.removeprefix("Art. ").replace("º", "")


def _is_cited(chunk: Chunk, cited: list[tuple[str | None, str]]) -> bool:
    norma, number = _key(chunk)
    return any(number == n and (c is None or c == norma) for c, n in cited)


def is_grounded(text: str, retrieved: list[Chunk]) -> bool:
    cited = cited_articles(text)
    return bool(cited) and all(_is_cited_by_any(item, retrieved) for item in cited)


def _is_cited_by_any(item: tuple[str | None, str], retrieved: list[Chunk]) -> bool:
    return any(_is_cited(chunk, [item]) for chunk in retrieved)


def audit(path: Path | None, question: str, retrieved: list[Chunk], grounded: bool) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"question": question, "retrieved": [f"{c.norma} {c.artigo}" for c in retrieved], "grounded": grounded}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def answer(question: str, index: Index, provider: Provider, min_score: float | None = None, k: int = 3,
           embed: Callable[[list[str]], list[list[float]]] | None = None, audit_path: Path | None = None) -> Answer:
    threshold = DEFAULT_MIN_SCORE[index.mode] if min_score is None else min_score
    hits = index.search(question, k, embed)
    retrieved = [chunk for chunk, _ in hits]
    if not hits or hits[0][1] < threshold:
        audit(audit_path, question, [], False)
        return Answer(answer=NOT_FOUND, citations=[], grounded=False)
    context = "\n\n".join(f"[{c.norma}, {c.artigo}]\n{c.text}" for c in retrieved)
    try:
        text = provider.reply(SYSTEM_PROMPT, f"Trechos:\n{context}\n\nPergunta: {question}")
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        audit(audit_path, question, retrieved, False)
        return Answer(answer=LLM_DOWN, citations=[], grounded=False)
    grounded = is_grounded(text, retrieved)
    cited = cited_articles(text)
    shown = [c for c in retrieved if _is_cited(c, cited)] if grounded else []
    audit(audit_path, question, retrieved, grounded)
    return Answer(
        answer=text,
        citations=[Citation(norma=c.norma, artigo=c.artigo, trecho=c.text[:300]) for c in shown],
        grounded=grounded,
    )
