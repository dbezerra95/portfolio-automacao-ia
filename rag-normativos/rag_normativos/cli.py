import argparse
import os
from pathlib import Path

from rag_normativos.core import Answer, OpenAICompatible, ask, build_index, load_index


def render(result: Answer) -> str:
    lines = [result.answer, ""]
    for citation in result.citations:
        lines.append(f"- {citation.norma}, {citation.artigo}: {citation.trecho}")
    lines.append(f"grounded: {str(result.grounded).lower()}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Perguntas sobre a LC 108/2001 e a LC 109/2001")
    commands = parser.add_subparsers(dest="command", required=True)
    index_parser = commands.add_parser("index", help="monta o índice a partir de data/")
    index_parser.add_argument("--embeddings", action="store_true", help="gera embeddings no endpoint compatível com OpenAI")
    ask_parser = commands.add_parser("ask", help="responde uma pergunta com citações")
    ask_parser.add_argument("question")
    args = parser.parse_args()
    if args.command == "index":
        index = build_index(Path(os.environ.get("DATA_DIR", "data")), args.embeddings)
        path = Path(os.environ.get("INDEX_PATH", "index/chunks.json"))
        index.save(path)
        print(f"{len(index.chunks)} artigos indexados em {path} ({index.mode})")
    else:
        print(render(ask(args.question, load_index(), OpenAICompatible())))
