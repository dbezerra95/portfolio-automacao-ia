"""Demonstração local da cascata."""
import argparse
import os
from pathlib import Path

from pyspark.ml.evaluation import MulticlassClassificationEvaluator
from pyspark.ml.tuning import CrossValidator, ParamGridBuilder
from pyspark.sql import SparkSession, functions as F
from rich.console import Console
from rich.table import Table

from .data import SECTORS, generate
from .llm import FakeProvider, OpenAIProvider, metrics, route
from .model import pipeline, predict


def main() -> None:
    parser = argparse.ArgumentParser(description="Cascata CNAE com dados sintéticos")
    parser.add_argument("--rows", type=int, default=2000)
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--input-price", type=float, default=0.60, help="US$ por milhão de tokens de entrada")
    parser.add_argument("--output-price", type=float, default=2.40, help="US$ por milhão de tokens de saída")
    parser.add_argument("--provider", choices=["fake", "openai"], default="fake")
    parser.add_argument("--svg", type=Path, help="salva a tabela demonstrativa em SVG")
    args = parser.parse_args()
    if args.rows < 60 or args.input_price < 0 or args.output_price < 0:
        parser.error("use ao menos 60 linhas e preços não negativos")
    if args.provider == "openai":
        provider = OpenAIProvider(os.environ["OPENAI_BASE_URL"], os.environ["OPENAI_MODEL"], os.environ["OPENAI_API_KEY"])
    else:
        provider = FakeProvider()
    data = generate(args.rows)
    split = int(len(data) * 0.8)
    training, test = data[:split], data[split:]
    examples = [next(item for item in training if item[1] == label) for label in SECTORS]
    spark = SparkSession.builder.master("local[1]").appName("spark-ai-cascade").config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "1").getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    try:
        train_df = spark.createDataFrame(training, ["text", "label"])
        # Avaliação cruzada no treino; o teste permanece separado.
        cv = CrossValidator(estimator=pipeline(), estimatorParamMaps=ParamGridBuilder().build(),
                            evaluator=MulticlassClassificationEvaluator(labelCol="label_index", metricName="accuracy"),
                            numFolds=2, seed=42, parallelism=1)
        model = cv.fit(train_df).bestModel
        predictions = predict(model, spark.createDataFrame(test, ["text", "label"]))
        result = metrics(route(predictions, provider, examples, args.threshold), args.input_price, args.output_price)
        majority = max(SECTORS, key=lambda label: sum(item[1] == label for item in training))
        baseline = spark.createDataFrame(test, ["text", "label"]).agg(F.avg((F.col("label") == majority).cast("double"))).first()[0]
        console = Console(record=True, width=100)
        title = "dados sintéticos; etapa LLM simulada" if args.provider == "fake" else "dados sintéticos; LLM externo"
        if args.provider == "fake":
            console.print("Na réplica, a etapa LLM é simulada; o ganho real da LLM foi medido no projeto original")
        table = Table(title=title)
        for name in ("Etapa", "Acurácia", "% para LLM"):
            table.add_column(name, justify="left" if name == "Etapa" else "right")
        for name, accuracy, routed in [("Classe majoritária", baseline, 0), ("C0 · palavras-chave", result["c0"], 0), ("C1/C2 · Spark ML", result["c2"], 0), ("C3 · linhas roteadas", result["c3"], result["routed"]), ("Cascata final", result["final"], result["routed"])]:
            table.add_row(name, f"{accuracy:.1%}" if accuracy is not None else "n/a", f"{routed:.1%}")
        console.print(table)
        if args.svg:
            console.save_svg(str(args.svg), title=title)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
