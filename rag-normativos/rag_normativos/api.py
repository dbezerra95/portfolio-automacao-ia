from fastapi import FastAPI
from pydantic import BaseModel

from rag_normativos.core import Answer, OpenAICompatible, ask, load_index


class Question(BaseModel):
    question: str


app = FastAPI(title="RAG de normativos")


@app.post("/ask", response_model=Answer)
def ask_endpoint(request: Question) -> Answer:
    return ask(request.question, load_index(), OpenAICompatible())
