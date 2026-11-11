import csv
import io
import os
import time
from html import escape

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv("LEGACY_SECRET", "local-demo-only"), same_site="lax")
ROWS = [
    ("P001", "A*** S***", "2026-10", "100.00"),
    ("P002", "B*** O***", "2026-10", "205.00"),
    ("P003", "C*** L***", "2026-10", "150.00"),
    ("P004", "D*** M***", "2026-10", "300.00"),
    ("P005", "E*** R***", "2026-10", "99.00"),
]


def page(body: str) -> HTMLResponse:
    return HTMLResponse('<html lang="pt-BR"><head><meta charset="utf-8"><title>Previdência Demo</title><style>body{font:14px Arial;background:#e1e5e8;color:#222;margin:30px} .window{background:#fff;border:2px solid #526879;max-width:950px;margin:auto;padding:12px} h1{font-size:19px;background:#35536a;color:white;margin:-12px -12px 20px;padding:12px} table{border-collapse:collapse;width:100%;margin:20px 0} td,th{border:1px solid #8f9faa;padding:8px;text-align:left} th{background:#c9d4dc} a{color:#003d85} button,input{padding:5px} .bar{background:#e9edef;padding:12px}</style></head><body><div class="window"><h1>Sistema de Previdência Complementar • Demonstração</h1>' + body + '</div></body></html>')


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Response:
    if request.session.get("authenticated"):
        return RedirectResponse("/contribuicoes", status_code=303)
    return page('<h2>Acesso ao sistema</h2><form method="post" action="/login"><p>Usuário: <input name="username" required></p><p>Senha: <input type="password" name="password" required></p><button>Entrar</button></form>')


@app.post("/login")
def login(request: Request, username: str = Form(), password: str = Form()) -> Response:
    if username != os.getenv("LEGACY_USER") or password != os.getenv("LEGACY_PASSWORD") or not username or not password:
        return HTMLResponse("Credenciais inválidas", status_code=401)
    request.session["authenticated"] = True
    return RedirectResponse("/contribuicoes", status_code=303)


@app.get("/contribuicoes", response_class=HTMLResponse)
def contributions(request: Request, competencia: str = "2026-10", pagina: int = 1) -> Response:
    if not request.session.get("authenticated"):
        return RedirectResponse("/", status_code=303)
    time.sleep(max(0, float(os.getenv("LEGACY_DELAY_SECONDS", "0"))))
    rows = [row for row in ROWS if row[2] == competencia]
    pagina = max(1, pagina)
    table = "".join("<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>" for row in rows[(pagina - 1) * 2:pagina * 2])
    links = " ".join(f'<a href="?competencia={escape(competencia, quote=True)}&amp;pagina={n}">{n}</a>' for n in range(1, (len(rows) + 1) // 2 + 1))
    return page(f'<div class="bar"><form method="get">Competência: <input name="competencia" type="month" value="{escape(competencia, quote=True)}" required> <button>Consultar</button></form></div><h2>Contribuições</h2><a href="/exportar?competencia={escape(competencia, quote=True)}">Exportar relatório</a><table><thead><tr><th>Participante</th><th>Nome</th><th>Competência</th><th>Valor (R$)</th></tr></thead><tbody>{table}</tbody></table><p>Páginas: {links}</p><small>Dados inteiramente fictícios</small>')


@app.get("/exportar")
def export(request: Request, competencia: str) -> Response:
    if not request.session.get("authenticated"):
        return RedirectResponse("/", status_code=303)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["participant_id", "name", "competencia", "valor"])
    writer.writerows(row for row in ROWS if row[2] == competencia)
    return Response(buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="contribuicoes.csv"'})
