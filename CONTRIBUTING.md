# Como contribuir

Obrigado por querer ajudar. Este guia é curto de propósito.

## Antes de tudo: nada de dado real

**Nunca** inclua conversas, nomes, telefones, CPFs ou qualquer dado de pessoas ou empresas reais
em issues, pull requests, testes ou exemplos. Use o gerador em [`synthetic/`](synthetic) ou
invente. Se você encontrou um erro numa conversa real, reescreva um exemplo mínimo com dados
falsos que reproduza o problema.

## Preparando o ambiente

```bash
uv sync --all-packages
uv run pytest
cd frontend && npm install
```

`pytest` roda sem banco nem Docker (SQLite em memória). Veja o [README](README.md#desenvolvimento)
para rodar com PostgreSQL.

## Antes de abrir o pull request

```bash
uv run ruff check . && uv run ruff format .
uv run mypy backend/src synthetic/src evals/src training/src
uv run pytest
cd frontend && npm run lint && npm run typecheck && npm run build
```

A CI roda exatamente isso, mais a suíte em PostgreSQL e o build das imagens Docker.

## Convenções

- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/pt-br/)
  (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`…), em português ou inglês.
- **Código:** identificadores em inglês; mensagens ao usuário, playbooks e documentação em
  português do Brasil.
- **Testes:** toda correção vem com um teste que falhava antes. Toda regra de playbook nova vem
  com um caso positivo e um negativo (ex.: a frase proibida e a mesma frase negada).
- **Tipos:** o backend passa em `mypy --strict`.
- **Migrations:** mudou um modelo? `cd backend && uv run alembic revision --autogenerate -m "..."`
  e revise o arquivo gerado.
- **Decisões:** escolhas técnicas que alguém pode questionar depois entram em
  [docs/DECISOES.md](docs/DECISOES.md).

## Contribuições que ajudam muito

- **Playbooks de novos setores** (veja [`playbooks/`](playbooks)): não exige programar.
- **Casos difíceis** para a suíte de avaliação: frases que o sistema erra (sempre sintéticas).
- **Formatos de export do WhatsApp** que o parser não reconhece: abra uma issue com as três
  primeiras linhas do arquivo, trocando nomes e números por dados falsos.

## Segurança

Vulnerabilidades não vão em issue pública. Veja [SECURITY.md](SECURITY.md).
