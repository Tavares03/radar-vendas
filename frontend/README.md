# Painel do Radar de Vendas

Next.js 16 (App Router, `cacheComponents`), React 19, Tailwind 4. Fala só com a API do Radar,
pela própria origem: `/api/*` é repassado para `BACKEND_URL` (padrão `http://127.0.0.1:8000`),
então não há CORS e o cookie de sessão é first-party.

```bash
npm install
npm run dev          # http://localhost:3000 (a API precisa estar em 127.0.0.1:8000)
npm run lint
npm run typecheck    # gera os tipos das rotas (next typegen) e roda o tsc
npm test             # Vitest + Testing Library
npm run build
```

## Como está organizado

| Pasta | O que tem |
|---|---|
| `src/app/login/` | entrada; a única página fora do painel |
| `src/app/(painel)/` | as páginas do painel. Cada `page.tsx` é fino e só envolve a view (componente cliente) num `Suspense` |
| `src/components/` | peças compartilhadas: bolha de mensagem, texto com destaques, painel da nota, revisão de alerta, gráfico semanal, casca do app |
| `src/lib/api/` | cliente tipado (`openapi-fetch`) e hooks SWR; `openapi.json` e `schema.d.ts` são gerados |
| `src/lib/highlight.ts` | divide o texto em trechos: tarja de dado pessoal, evidência de alerta e texto comum |
| `src/lib/format.ts` | rótulos e datas em português |

Os dados são buscados no navegador, com SWR: as páginas são estáticas e a sessão nunca é lida no
servidor do Next. Um 401 leva para `/login`. As permissões vêm de `GET /api/v1/auth/me` e o
painel esconde o que o papel não pode fazer; quem decide de verdade é a API.

## Contrato com a API

Os tipos vêm do OpenAPI da API. Ao mudar um endpoint:

```bash
# na raiz do repositório
uv run python scripts/export_openapi.py
cd frontend && npm run api:types
```

Um teste do backend falha se o `openapi.json` ficar desatualizado, e a CI falha se o
`schema.d.ts` não corresponder ao `openapi.json`.

## Identidade visual

O painel é a mesa de um auditor. A evidência de um alerta aparece como marca-texto na cor da
severidade (`mark.evidencia[data-severity]`), e dado pessoal mascarado aparece como tarja
(`.tarja`). Fora isso, papel claro e tinta azul-escura: cor forte só onde há severidade. A fonte
é a Atkinson Hyperlegible Next, desenhada para leitura atenta. Os tokens ficam em
`src/app/globals.css`.
