# Registro de decisões

Decisões técnicas do Radar de Vendas, com o que foi considerado e por quê. Formato curto, em
ordem cronológica. Decisão nova entra no fim; decisão revista ganha uma linha "Revisão".

---

## D01 — Monorepo com uv workspace
**Decisão:** um repositório, um `uv.lock`, quatro pacotes Python (`backend`, `synthetic`,
`evals`, `training`) e o `frontend` em Node.
**Alternativas:** repositórios separados; Poetry; pip + requirements.
**Motivo:** o gerador sintético, os evals e o Space reutilizam o pacote `radar`. Um lock só evita
"funciona no meu pacote". O uv resolve e instala em segundos e é gratuito.

## D02 — Lógica pura no pacote `radar`, sem depender da API
**Decisão:** parser, privacidade, playbooks, análise e LLM são funções e classes sem FastAPI nem
banco. API, worker, CLI, evals e Space são cascas finas.
**Motivo:** testabilidade, e o Space do Hugging Face consegue rodar o mesmo código sem banco.

## D03 — SQLAlchemy 2 síncrono + psycopg 3
**Alternativas:** asyncpg + SQLAlchemy async.
**Motivo:** o trabalho pesado (transcrição, modelos, LLM) acontece no worker, que é síncrono e
CPU-bound. Async no banco só traria complexidade (sessões, lazy loading, testes) sem ganho real
para o volume esperado. Os endpoints são `def` e rodam no threadpool do FastAPI.

## D04 — Testes em SQLite por padrão, PostgreSQL na CI
**Decisão:** tipos portáveis (`JSONType`, `EmbeddingType`, `UtcDateTime`) permitem rodar `pytest`
sem nenhum serviço. A CI repete a suíte inteira em PostgreSQL 17 + pgvector e valida as migrations
(`upgrade`, `check` de drift e `downgrade`).
**Motivo:** contribuição com atrito zero sem abrir mão de validar o dialeto real.

## D05 — Multi-tenant por coluna `tenant_id` com filtro automático
**Decisão:** toda tabela de dados herda `TenantScoped`. A sessão carrega o `tenant_id` do
principal autenticado; um listener aplica o filtro em todo `SELECT` e um guarda de `flush`
preenche ou recusa escritas de outra empresa. Recurso de outra empresa responde 404.
**Alternativas:** um schema por empresa; Row Level Security do PostgreSQL.
**Motivo:** simples, testável e portável para SQLite. RLS fica no roadmap como defesa adicional.

## D06 — Sessão em cookie httpOnly + tokens de API
**Decisão:** o painel usa JWT (HS256) em cookie `httpOnly`, `SameSite=Lax`. Integrações usam
`Authorization: Bearer rdr_…` (token de API com escopos `ingest`/`read`, guardado como SHA-256).
Revogação de sessões por `session_version` no usuário (incrementa ao trocar a senha).
**Alternativas:** token em `localStorage`; sessão no Redis.
**Motivo:** nada sensível acessível a JavaScript; revogação sem estado extra.
**CSRF:** requisições com cookie e `Sec-Fetch-Site: cross-site` são recusadas, além do SameSite.

## D07 — Argon2id para senhas
**Motivo:** recomendação atual da OWASP. Login de e-mail inexistente gasta o mesmo tempo
(`burn_time`) para não revelar quem tem conta.

## D08 — Texto bruto cifrado em repouso
**Decisão:** o texto original das mensagens é cifrado com Fernet (chave derivada de
`RADAR_SECRET_KEY` por HKDF). O painel e os LLMs trabalham com o texto mascarado.
**Motivo:** minimização (LGPD): um vazamento do banco não expõe CPF, telefone ou conversa em
claro, e a política de retenção pode apagar o bruto mantendo a análise.

## D09 — Fila: RQ sobre Valkey, com modos `inline` e `sync`
**Alternativas:** Celery; Arq; Dramatiq; só `BackgroundTasks`.
**Motivo:** RQ é o mais simples que resolve (retry, agendamento, falhas visíveis). Valkey é o
fork BSD do Redis, mantido pela Linux Foundation. O modo `inline` (thread na própria API) deixa
o modo leve funcionar sem Valkey; `sync` torna os testes determinísticos.
**Detalhe:** o worker usa `SimpleWorker` (sem fork por job) para manter os modelos ONNX e o
Whisper carregados em memória.

## D10 — Frontend fala com a API pelo mesmo domínio
**Decisão:** o Next.js reescreve `/api/*` para o backend (`rewrites`). O navegador só conhece
uma origem.
**Motivo:** sem CORS, cookie first-party, um único endereço para publicar.
**Detalhe:** não usamos `proxy.ts` (ex-middleware) para isso porque ele bufferiza o corpo e
limitaria o upload de exports grandes.

## D11 — Portas 5433 e 6380 no host
**Motivo:** 5432 e 6379 costumam estar ocupadas por outro Postgres/Redis na máquina de quem
desenvolve. Dentro da rede do Compose as portas continuam as padrões.

## D12 — Licenças
**Decisão:** Apache-2.0 para código e modelos; CC BY 4.0 para o dataset sintético.
**Motivo:** concessão explícita de patentes, compatível com o BERTimbau (MIT) e com uso comercial
por pequenas empresas — que é o público do projeto.

## D13 — Provedores de LLM por um único cliente compatível com OpenAI
**Decisão:** Groq, Gemini (endpoint OpenAI-compatible), OpenRouter e Ollama são acessados pelo
mesmo cliente HTTP (`/chat/completions`), com saída estruturada por `json_schema` quando o
provedor suporta e reparo de JSON quando não.
**Alternativas:** SDK de cada provedor; LiteLLM.
**Motivo:** menos dependências, comportamento idêntico entre provedores, e o failover vira uma
lista ordenada. Limites medidos nos planos gratuitos (ex.: 8 mil tokens/min na Groq) viram
configuração por provedor.
