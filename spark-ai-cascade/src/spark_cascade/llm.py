"""Provedores C3 e roteamento por confiança."""
import json
from typing import Protocol
from urllib.request import Request, urlopen

from pyspark.sql import DataFrame, functions as F
from pyspark.sql.types import IntegerType, StringType, StructField, StructType

from .data import SECTORS


class Provider(Protocol):
    def classify(self, text: str, candidates: list[tuple[str, float]], examples: list[tuple[str, str]]) -> tuple[str, int, int]:
        """Retorna seção e contagens de tokens de entrada e saída."""
        ...


class FakeProvider:
    """Simulação determinística, sem acesso à rede ou ao rótulo verdadeiro."""
    def classify(self, text: str, candidates: list[tuple[str, float]], examples: list[tuple[str, str]]) -> tuple[str, int, int]:
        return candidates[0][0], 100 + len(text.split()) + len(examples) * 8, 1


class OpenAIProvider:
    """API de chat compatível com OpenAI; preços são configurados separadamente."""
    def __init__(self, base_url: str, model: str, api_key: str) -> None:
        self.base_url, self.model, self.api_key = base_url.rstrip("/"), model, api_key

    def classify(self, text: str, candidates: list[tuple[str, float]], examples: list[tuple[str, str]]) -> tuple[str, int, int]:
        prompt = f"Classifique a seção CNAE. Retorne somente a letra A a U. Seções: {[(k, v[0]) for k, v in SECTORS.items()]}. Exemplos: {examples}. Candidatos (seção, probabilidade): {candidates}. Nome: {text}"
        body = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}).encode()
        request = Request(f"{self.base_url}/chat/completions", data=body, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        with urlopen(request, timeout=60) as response:
            result = json.load(response)
        label = result["choices"][0]["message"]["content"].strip().upper()
        if len(label) != 1 or not "A" <= label <= "U":
            raise ValueError(f"Resposta de seção inválida: {label!r}")
        return label, result["usage"]["prompt_tokens"], result["usage"]["completion_tokens"]


def route(rows: DataFrame, provider: Provider, examples: list[tuple[str, str]], threshold: float) -> DataFrame:
    """Filtra no Spark e envia ao provedor apenas linhas abaixo do limiar."""
    routed = rows.filter(F.col("confidence") < threshold).select("text", "label", "c0", "c2", "candidates").collect()
    results = []
    for row in routed:
        candidates = [(candidate.label, candidate.probability) for candidate in row.candidates]
        label, input_tokens, output_tokens = provider.classify(row.text, candidates, examples)
        results.append((row.label, row.c0, row.c2, label, True, input_tokens, output_tokens))
    schema = StructType([StructField(name, StringType(), False) for name in ("label", "c0", "c2", "final")])
    schema = schema.add("routed", "boolean", False).add("input_tokens", IntegerType(), False).add("output_tokens", IntegerType(), False)
    answered = rows.sparkSession.createDataFrame(results, schema)
    untouched = (rows.filter(F.col("confidence") >= threshold)
                 .select("label", "c0", "c2", F.col("c2").alias("final"), F.lit(False).alias("routed"),
                         F.lit(0).alias("input_tokens"), F.lit(0).alias("output_tokens")))
    return untouched.unionByName(answered)


def metrics(rows: DataFrame, input_price: float, output_price: float) -> dict:
    """Agrega acurácias, cobertura e custo; C3 considera apenas linhas roteadas."""
    result = rows.agg(
        F.count("*").alias("n"),
        *[F.avg((F.col(key) == F.col("label")).cast("double")).alias(key) for key in ("c0", "c2", "final")],
        F.avg(F.when(F.col("routed"), (F.col("final") == F.col("label")).cast("double"))).alias("c3"),
        F.avg(F.col("routed").cast("double")).alias("routed"),
        (F.sum(F.col("input_tokens") * input_price + F.col("output_tokens") * output_price) / 1_000_000).alias("cost"),
    ).first().asDict()
    if not result.pop("n"):
        raise ValueError("O conjunto de avaliação está vazio")
    return result
