# Monitor judicial diário
> Acompanha publicações e movimentações para ajudar no controle de prazos sem abrir portais todos os dias.

**O que este projeto prova**
- Integração com três bases públicas do Judiciário: DataJud e DJEN do CNJ e PJe do TJDFT, por número de processo, sem login e sem dado de pessoa.
- Robustez com novas tentativas e alerta de falha.
- Auditoria e privacidade por desenho.

## Demonstração
![Execução com dados fictícios](docs/execucao.svg)
Execução simulada com respostas fictícias das APIs.

## Como funciona
```mermaid
flowchart LR
    A[Lista de processos] --> B[DataJud, DJEN e PJe TJDFT]
    B --> C[Comparação com estado]
    C --> D[Console ou webhook]
    D --> E[Estado e auditoria]
```
- Consulta comunicações do DJEN, movimentações do PJe nos dois graus e classe, assuntos, órgão julgador e movimentações do DataJud para cada número. O DataJud não fornece texto de decisão nem partes.
- A primeira execução informa todos os itens encontrados; as seguintes informam apenas novidades.
- Falhas geram alerta e retorno de erro para o serviço.
- A auditoria registra contagens, duração e tipo de erro por fonte.

## Decisões de projeto
- Não há busca por CPF ou nome: somente números de processo, como decisão de privacidade alinhada à LGPD.
- O estado idempotente guarda identificadores após cada notificação bem-sucedida, permitindo retomada após falhas.
- O alerta no console ou webhook e a unidade OnFailure tornam falhas visíveis; o hash do processo reduz exposição no log.

<details>
<summary>Detalhes técnicos: stack, como rodar e testes</summary>

Python, uv, httpx, Pydantic, PyYAML e Rich. As URLs dos dois graus podem ser ajustadas no YAML. O número de exemplo é fictício; substitua-o antes de consultar APIs reais.

```bash
uv sync
uv run judicial-monitor run --config config.example.yaml --dry-run
uv run pytest -q
```

Configure `DATAJUD_API_KEY` com a chave pública publicada pelo CNJ na [documentação do DataJud](https://datajud-wiki.cnj.jus.br/api-publica/acesso/). Os tribunais DataJud mapeados são TJDFT e TJSP; outros informam erro de configuração.

O dry-run consulta as APIs e escreve auditoria, mas imprime notificações e não altera o estado. Sem dry-run, `DISCORD_WEBHOOK_URL` define o webhook; sem ela, usa-se o console. Veja `.env.example` e exporte a variável no shell ou configure o arquivo `.env` para o serviço. Estado e auditoria são relativos ao arquivo de configuração. Os arquivos em `deploy/` são exemplos de unidades de usuário systemd; ajuste os caminhos e ative o timer. Horário usa o fuso do sistema. As APIs externas podem mudar ou ficar indisponíveis.
</details>
