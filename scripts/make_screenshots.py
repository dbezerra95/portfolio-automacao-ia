from datetime import UTC, date, datetime
from html import escape
from pathlib import Path
import contextlib
import io
import os
import sys
import tempfile
import time

import httpx
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

ROOT = Path(__file__).resolve().parents[1]
for project in ("whatsapp-ai-agent", "lead-qualifier-agent", "llm-router", "rpa-collectors", "ai-radar"):
    sys.path.insert(0, str(ROOT / project))
    (ROOT / project / "docs").mkdir(exist_ok=True)

from app import create_app
from qualifier.core import Message, QUESTIONS, SAFE_HANDOFF, conversation_step
from llm_router import Provider, Router
from collectors import parse_books, parse_quotes, save_records
from radar.core import Item, run


class ChatProvider:
    def reply(self, text: str) -> str:
        return "Olá! Informe o modelo do veículo para consultarmos a peça."


class LeadProvider:
    def reply(self, system: str, message: str) -> str:
        import json
        text = message.split("Mensagem do lead: ", 1)[1]
        responses = {
            "Sou Ana Souza, da Oficina Horizonte. Tenho uma dívida de R$ 50.000 por uma cobrança indevida.": {
                "name": "Ana Souza", "company": "Oficina Horizonte", "debt_amount": "R$ 50.000", "situation": "cobrança indevida"
            },
            "E-mail": {"channel": "E-mail"},
        }
        return json.dumps(responses.get(text, {}), ensure_ascii=False)


class RadarProvider:
    def summarize(self, item: Item) -> str:
        return item.description


def chat_html(subtitle: str, messages: list[tuple[str, str, str]]) -> str:
    rows = "".join(f'<div class="row {escape(kind)}"><div class="bubble"><small>{escape(label)}</small>{escape(text)}</div></div>' for kind, label, text in messages)
    return f'''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><style>
    *{{box-sizing:border-box}} body{{margin:0;background:#e9edf2;color:#172c43;font:18px Arial,sans-serif;padding:42px 65px}}
    .app{{background:#fff;border:1px solid #d9e2eb;border-radius:16px;overflow:hidden;box-shadow:0 10px 32px #1833501a}}
    header{{background:#253e5b;color:#fff;padding:25px 32px}} h1{{font-size:23px;margin:0 0 6px}} header p{{margin:0;color:#c5d3e2;font-size:15px}}
    main{{padding:25px 32px;background:#f3f6f9}} .row{{display:flex;margin:11px 0}} .right{{justify-content:flex-end}}
    .bubble{{max-width:75%;padding:12px 16px;line-height:1.4;border-radius:12px;background:#fff;border:1px solid #dce4ec}}
    .right .bubble{{background:#dceaf6;border-color:#ccdeee}} small{{display:block;color:#526c85;font-size:13px;font-weight:bold;margin-bottom:5px}}
    .note{{justify-content:center}} .note .bubble{{max-width:95%;background:#e3e9ef;color:#42586e;font-size:14px;padding:7px 14px;text-align:center}}
    .note small{{display:none}}</style><div class="app"><header><h1>Atendimento automatizado</h1><p>{escape(subtitle)}</p></header><main>{rows}</main></div></html>'''


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as playwright:
        temp = Path(tmp)
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1000, "height": 900}, device_scale_factor=2)
        client = TestClient(create_app(str(temp / "chat.db"), ChatProvider()))
        messages = []
        def send(sender: str, text: str, from_me: bool = False) -> dict:
            response = client.post("/webhook", json={"sender": sender, "text": text, "from_me": from_me, "timestamp": datetime.now(UTC).isoformat()})
            response.raise_for_status()
            return response.json()
        question = "Olá, vocês têm filtro de óleo?"
        result = send("cliente", question)
        assert result["status"] == "customer" and result["reply"]
        messages.extend([("left", "Cliente", question), ("right", "Assistente", result["reply"])])
        human = "Olá! Vou verificar a peça para você."
        assert send("cliente", human, True)["status"] == "human_handoff"
        messages.append(("right", "Atendente humano", human))
        followup = "Meu carro é um modelo 2020."
        result = send("cliente", followup)
        assert result == {"status": "paused", "reply": None}
        messages.extend([("left", "Cliente", followup), ("note", "", "bot pausado: atendimento humano")])
        supplier = "Olá, sou fornecedor de peças para atacado."
        result = send("fornecedor", supplier)
        assert result == {"status": "supplier", "reply": None}
        messages.extend([("left", "Fornecedor", supplier), ("note", "", "Fornecedor encaminhado para triagem, sem resposta automática")])
        page.set_content(chat_html("Loja de autopeças • conversa de demonstração", messages))
        page.screenshot(path=str(ROOT / "whatsapp-ai-agent/docs/conversa.png"), full_page=True)

        history = []
        provider = LeadProvider()
        messages = [("right", "Assistente", QUESTIONS["name"])]
        for value in ("Sou Ana Souza, da Oficina Horizonte. Tenho uma dívida de R$ 50.000 por uma cobrança indevida.", "qual a chance de eu ganhar?", "E-mail"):
            result = conversation_step(history, value, provider)
            messages.append(("left", "Lead", value))
            messages.append(("right", "Assistente", result.reply))
            if result.needs_handoff:
                assert result.reply == SAFE_HANDOFF
                messages.append(("note", "", "encaminhamento jurídico sinalizado"))
            history.extend([Message(role="user", content=value), Message(role="assistant", content=result.reply, field=result.next_field)])
        assert result.qualified and result.handoff is not None
        page.set_content(chat_html("Triagem inicial • dados fictícios", messages))
        page.screenshot(path=str(ROOT / "lead-qualifier-agent/docs/conversa.png"), full_page=True)
        table = Table(show_header=False, box=None, padding=(0, 2))
        for label, value in (("Nome", result.handoff.name), ("Empresa", result.handoff.company), ("Dívida", "R$ " + f"{result.handoff.debt_amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")), ("Situação", result.handoff.situation), ("Canal", result.handoff.channel)):
            table.add_row(f"[bold cyan]{label}[/]", str(value))
        console = Console(record=True, width=85)
        console.print(Panel(table, title="Handoff para advogado", subtitle="Triagem concluída", border_style="blue"))
        console.save_svg(str(ROOT / "lead-qualifier-agent/docs/handoff.svg"), title="Resumo de qualificação")

        attempts = []
        def handler(request: httpx.Request) -> httpx.Response:
            start = time.monotonic()
            name = request.url.host.split(".")[0]
            time.sleep({"primario": 0.12, "secundario": 0.09, "reserva": 0.65}[name])
            if name == "primario":
                response, status = httpx.Response(429), "HTTP 429"
            elif name == "secundario":
                response, status = httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}), "Conteúdo vazio"
            else:
                response, status = httpx.Response(200, json={"choices": [{"message": {"content": "Automação reduz tarefas repetitivas e libera tempo para análise."}}]}), "Resposta recebida"
            attempts.append((name, status, (time.monotonic() - start) * 1000))
            return response
        os.environ["SCREENSHOT_FAKE_KEY"] = "ficticia"
        providers = [Provider(name=n, base_url=f"https://{n}.example/v1", model="ficticio", api_key_env="SCREENSHOT_FAKE_KEY") for n in ("primario", "secundario", "reserva")]
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            routed = Router(providers, http).route("Explique automação")
        table = Table(title="Tentativas de provedores", header_style="bold cyan")
        for col in ("Provedor", "Status", "Latência (simulada)"):
            table.add_column(col)
        for name, status, latency in attempts:
            table.add_row(name, status, f"{latency:.2f} ms")
        console = Console(record=True, width=92)
        console.print(table)
        console.print("Provedores e respostas simulados para demonstração.")
        console.print(Panel(routed.answer, title=f"Resposta • {routed.provider}", border_style="blue"))
        console.save_svg(str(ROOT / "llm-router/docs/fallback.svg"), title="Fallback entre provedores")

        fixtures = ROOT / "rpa-collectors/tests/fixtures"
        records = parse_books((fixtures / "books.html").read_text()) + parse_quotes((fixtures / "quotes.html").read_text())
        first = save_records(records, temp / "records.db")
        second = save_records(records, temp / "records.db")
        console = Console(record=True, width=95)
        console.print(Panel(f"1ª execução: criados {first['created']}  |  atualizados {first['updated']}  |  inalterados {first['unchanged']}\n2ª execução: criados {second['created']}  |  atualizados {second['updated']}  |  inalterados {second['unchanged']}", title="Coleta idempotente", border_style="blue"))
        table = Table(title="Registros das fixtures", header_style="bold cyan")
        for col in ("Fonte", "Título", "Detalhe"):
            table.add_column(col)
        for record in records:
            table.add_row(record.source, record.title, record.detail)
        console.print(table)
        console.save_svg(str(ROOT / "rpa-collectors/docs/idempotencia.svg"), title="Coleta idempotente")

        config = temp / "sources.yaml"
        demo_items = {
            "modelos": ("Modelos", [
                ("Modelo Aurora reduz custo de análise de documentos", "A versão experimental usa menos memória em tarefas de leitura."),
                ("Modelo Brisa amplia suporte a idiomas regionais", "O novo conjunto de treinamento inclui variedades do português brasileiro."),
            ]),
            "ferramentas": ("Ferramentas", [
                ("Estúdio Farol facilita avaliação de assistentes", "A ferramenta reúne cenários de teste e compara respostas em um painel."),
                ("Biblioteca Ponte conecta dados a fluxos de IA", "O projeto adiciona conectores para consultar arquivos e bases internas."),
            ]),
            "pesquisa": ("Pesquisa", [
                ("Estudo investiga erros em resumos longos", "Pesquisadores propõem uma verificação de trechos para reduzir omissões."),
                ("Experimento avalia aprendizado com poucos exemplos", "Os resultados indicam ganhos em tarefas específicas com dados limitados."),
            ]),
        }
        config.write_text("".join(
            f"- category: {category}\n  url: https://example.com/{slug}\n"
            for slug, (category, _) in demo_items.items()
        ), encoding="utf-8")
        feeds = {
            slug: '<rss version="2.0"><channel><title>Demo</title>' + "".join(
                f"<item><title>{escape(title)}</title><link>https://example.com/{slug}/{index}</link>"
                f"<description>{escape(summary)}</description></item>"
                for index, (title, summary) in enumerate(items, start=1)
            ) + "</channel></rss>"
            for slug, (_, items) in demo_items.items()
        }
        with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=feeds[request.url.path.lstrip("/")])
        )) as http, contextlib.redirect_stdout(io.StringIO()):
            digest = run(config, temp / "state.json", temp / "out", RadarProvider(), http, dry_run=True, today=date(2026, 1, 1))
        assert digest is not None
        console = Console(record=True, width=140)
        from rich.markdown import Markdown
        console.print(Markdown(digest.read_text(encoding="utf-8")))
        console.save_svg(str(ROOT / "ai-radar/docs/digest.svg"), title="Digest do radar de IA")

        browser.close()


if __name__ == "__main__":
    main()
