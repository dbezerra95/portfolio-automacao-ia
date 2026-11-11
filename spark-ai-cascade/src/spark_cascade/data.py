"""Dados artificiais, sem nomes de pessoas ou empresas reais."""
import random

SECTORS = {
    "G": ("comércio", ["loja", "varejo", "mercado", "distribuidora"]),
    "C": ("indústria", ["fábrica", "indústria", "manufatura", "metalúrgica"]),
    "F": ("construção", ["construção", "obras", "edificações", "engenharia"]),
    "I": ("alimentação", ["restaurante", "lanchonete", "refeições", "cozinha"]),
    "Q": ("saúde", ["clínica", "laboratório", "saúde", "diagnóstico"]),
    "J": ("tecnologia", ["software", "informática", "sistemas", "tecnologia"]),
}


def generate(rows: int, seed: int = 42) -> list[tuple[str, str]]:
    """Gera nomes de fantasia e rótulos balanceados com alguns nomes ambíguos."""
    rng = random.Random(seed)
    labels = list(SECTORS)
    syllables = ["zun", "qiv", "wex", "jop", "vuk", "xaz", "kef", "yot", "biv", "nux"]
    result = []
    for i in range(rows):
        label = labels[i % len(labels)]
        fantasy = "".join(rng.choices(syllables, k=4)) + str(i)
        word = rng.choice(SECTORS[label][1]) if rng.random() >= 0.2 else rng.choice(["soluções", "grupo", "serviços", "empreendimentos"])
        result.append((f"{word} {fantasy} empresarial", label))
    rng.shuffle(result)
    return result
