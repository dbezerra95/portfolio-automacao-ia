"""Treino e predições do modelo Spark."""
from pyspark.ml import Pipeline, PipelineModel
from pyspark.ml.classification import LogisticRegression
from pyspark.ml.feature import HashingTF, IDF, RegexTokenizer, StringIndexer
from pyspark.ml.functions import vector_to_array
from pyspark.sql import DataFrame, functions as F

from .data import SECTORS


def pipeline() -> Pipeline:
    """Monta o pipeline de classificação."""
    return Pipeline(stages=[
        StringIndexer(inputCol="label", outputCol="label_index"),
        RegexTokenizer(inputCol="text", outputCol="words", pattern=r"\W+"),
        HashingTF(inputCol="words", outputCol="tf", numFeatures=2**14),
        IDF(inputCol="tf", outputCol="features"),
        LogisticRegression(labelCol="label_index", featuresCol="features", family="multinomial", regParam=0.03, maxIter=20),
    ])


def train(data: DataFrame) -> PipelineModel:
    """Ajusta o pipeline no conjunto de treino."""
    return pipeline().fit(data)


def predict(model: PipelineModel, data: DataFrame) -> DataFrame:
    """Calcula rótulo, confiança e candidatos no Spark."""
    labels = model.stages[0].labels
    probabilities = vector_to_array("probability")
    candidates = F.array_sort(F.array(*[
        F.struct((-probabilities[i]).alias("order"), F.lit(label).alias("label"), probabilities[i].alias("probability"))
        for i, label in enumerate(labels)
    ]))
    c0 = F.lit("G")
    for label, (_, terms) in reversed(list(SECTORS.items())):
        c0 = F.when(F.arrays_overlap(F.col("words"), F.array(*[F.lit(term) for term in terms])), label).otherwise(c0)
    return (model.transform(data)
            .withColumn("confidence", F.array_max(probabilities))
            .withColumn("candidates", F.slice(candidates, 1, 3))
            .withColumn("c2", F.element_at("candidates", 1)["label"])
            .withColumn("c0", c0)
            .select("text", "label", "c0", "c2", "confidence", "candidates"))
