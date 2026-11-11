import pytest
from pyspark.sql import SparkSession

from spark_cascade.data import generate
from spark_cascade.llm import FakeProvider, metrics, route
from spark_cascade.model import predict, train


@pytest.fixture(scope="module")
def spark():
    session = SparkSession.builder.master("local[1]").appName("cascade-tests").config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "1").getOrCreate()
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


def test_pipeline(spark):
    data = generate(48)
    model = train(spark.createDataFrame(data[:36], ["text", "label"]))
    rows = predict(model, spark.createDataFrame(data[36:], ["text", "label"]))
    assert rows.count() == 12
    assert rows.filter("confidence < 0 OR confidence > 1 OR size(candidates) != 3").count() == 0


class CountingFake(FakeProvider):
    def __init__(self):
        self.calls = []

    def classify(self, text, candidates, examples):
        self.calls.append(text)
        return "Q", 100, 10


def test_routing_and_metrics(spark):
    rows = spark.createDataFrame([
        ("a", "Q", "G", "G", 0.3, [("G", 0.3)]),
        ("b", "G", "G", "G", 0.8, [("G", 0.8)]),
        ("c", "Q", "G", "G", 0.9, [("G", 0.9)]),
    ], "text string, label string, c0 string, c2 string, confidence double, candidates array<struct<label:string,probability:double>>")
    fake = CountingFake()
    result = route(rows, fake, [], 0.8)
    assert fake.calls == ["a"]
    values = metrics(result, 1, 2)
    assert values == {"c0": 1 / 3, "c2": 1 / 3, "final": 2 / 3, "c3": 1.0, "routed": 1 / 3, "cost": 0.00012}


@pytest.mark.parametrize("threshold, expected", [(0.0, []), (0.8, ["a"]), (1.0, ["a", "b"]), (1.01, ["a", "b", "c"])])
def test_threshold_edges(spark, threshold, expected):
    rows = spark.createDataFrame([
        ("a", "G", "G", "G", 0.0, [("G", 0.0)]),
        ("b", "G", "G", "G", 0.8, [("G", 0.8)]),
        ("c", "G", "G", "G", 1.0, [("G", 1.0)]),
    ], "text string, label string, c0 string, c2 string, confidence double, candidates array<struct<label:string,probability:double>>")
    fake = CountingFake()
    result = route(rows, fake, [], threshold)
    assert fake.calls == expected
    assert result.filter("routed").count() == len(expected)
    if not expected:
        assert metrics(result, 1, 2)["c3"] is None
