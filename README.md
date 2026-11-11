# Portfólio: Automação e IA aplicada

Cinco projetos Python demonstram soluções práticas para automatizar processos, integrar sistemas e aplicar IA com controle humano.

![CI](https://github.com/dbezerra95/portfolio-automacao-ia/actions/workflows/ci.yml/badge.svg)

## Em 30 segundos

- Automação de processos e RPA com coleta, normalização e integração de dados.
- IA aplicada com guardrails e supervisão humana em fluxos de atendimento e triagem.
- Engenharia com testes automatizados e CI para os cinco projetos.

## Projetos

| Projeto | Problema que resolve | Destaque técnico | Stack |
| --- | --- | --- | --- |
| [whatsapp-ai-agent](whatsapp-ai-agent/) | Triagem de mensagens repetitivas para uma loja de autopeças. | Webhook classifica mensagens e pausa o bot após atendimento humano; retorna a resposta sem envio real ao WhatsApp. | Python, FastAPI, HTTPX, SQLite |
| [llm-router](llm-router/) | Indisponibilidade ou resposta vazia de provedores de linguagem. | Cascata com fallback para falhas temporárias e registro de provedor e latência. | Python, HTTPX, Pydantic, TOML |
| [rpa-collectors](rpa-collectors/) | Coleta periódica de páginas públicas sem duplicar registros. | Chave natural e hash identificam criações, alterações e itens inalterados. | Python, Playwright, HTTPX, BeautifulSoup, SQLite |
| [lead-qualifier-agent](lead-qualifier-agent/) | Coleta inicial de informações para triagem em um escritório fictício. | Perguntas fixas, filtro de padrões e resumo estruturado para revisão por advogado. | Python, FastAPI, Pydantic, HTTPX |
| [ai-radar](ai-radar/) | Acompanhamento de fontes de IA e notícias já vistas. | Deduplicação de feeds, resumo por LLM e digest em Markdown para Discord ou console. | Python, HTTPX, feedparser, Pydantic, PyYAML |

## Requisitos

| Requisito | Onde ver |
| --- | --- |
| Automação de processos (RPA, integrações, scripts) | [rpa-collectors](rpa-collectors/), [ai-radar](ai-radar/) |
| APIs e integração de sistemas | [whatsapp-ai-agent](whatsapp-ai-agent/), [lead-qualifier-agent](lead-qualifier-agent/), [ai-radar](ai-radar/) |
| Uso prático de IA (LLMs, NLP, automação inteligente) | [whatsapp-ai-agent](whatsapp-ai-agent/), [llm-router](llm-router/), [lead-qualifier-agent](lead-qualifier-agent/), [ai-radar](ai-radar/) |
| Arquitetura e banco de dados | [rpa-collectors](rpa-collectors/), [whatsapp-ai-agent](whatsapp-ai-agent/) |
| Boas práticas e evitar over-engineering | [rpa-collectors](rpa-collectors/), [llm-router](llm-router/) |
| Monitorar resultados e evoluir as soluções | [rpa-collectors](rpa-collectors/), [llm-router](llm-router/), [ai-radar](ai-radar/) |

## Princípios

- Humano no loop onde há decisão, com encaminhamento para revisão.
- Fallback e resiliência diante de falhas de provedores e entregas.
- Idempotência nas coletas, com identificação de registros e alterações.
- Dados fictícios ou públicos, sem dado pessoal real.

```mermaid
flowchart LR
    A[Entrada de dados] --> B[Automação e robôs]
    B --> C[IA com guardrails]
    C --> D[Humano]
    D --> E[Sistemas e entrega]
```

## Como rodar

Entre na pasta de um projeto e execute:

```bash
cd nome-do-projeto
uv sync
uv run pytest -q
```

Consulte o README de cada projeto para executar suas funcionalidades e configurar eventuais integrações.

## Como regenerar as imagens

Na raiz, execute `uv run --with rich --with playwright python scripts/make_screenshots.py`; se necessário, instale o navegador com `uv run --with playwright playwright install chromium`. A página Swagger usa recursos carregados pela internet.

## Sobre

Réplicas simplificadas e reescritas de projetos reais em produção. Nenhum código, dado ou nome de cliente foi reutilizado.
