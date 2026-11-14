# Radar de Vendas

**Supervisor de vendas com IA para equipes que vendem pelo WhatsApp.** Lê as conversas da equipe
(texto e áudio), aponta riscos e oportunidades perdidas, dá uma nota explicável a cada
atendimento e ajuda o gestor a treinar os vendedores — em português, de graça e com LGPD em
primeiro lugar.

[![CI](https://github.com/Tavares03/radar-vendas/actions/workflows/ci.yml/badge.svg)](https://github.com/Tavares03/radar-vendas/actions/workflows/ci.yml)
[![Licença: Apache-2.0](https://img.shields.io/badge/licen%C3%A7a-Apache--2.0-blue.svg)](LICENSE)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)

> 🇬🇧 **English summary:** Radar de Vendas is an open-source "AI sales supervisor" for teams that
> sell over WhatsApp. It ingests chat exports (text and voice notes), masks personal data before
> any LLM call, flags compliance risks and missed opportunities with exact evidence, scores each
> conversation with explainable criteria, and coaches sellers. Brazilian Portuguese first, LGPD
> by design, and it runs at zero cost: local models plus free-tier LLM APIs, or 100% offline with
> Ollama. See [docs/PLANO.md](docs/PLANO.md) for the roadmap.

> **Estado:** em construção, fase por fase. O que já funciona está em
> [Status das fases](docs/PLANO.md#8-status-das-fases).

## Por que existe

Empresas pequenas e médias que vendem pelo WhatsApp (consórcio, seguros, imobiliárias, clínicas,
lojas) não conseguem ler todas as conversas da equipe. Sem ler, o gestor não vê:

- o vendedor que **promete o que não pode** ("contemplação garantida no primeiro mês");
- o cliente que disse "vou pensar" e **nunca mais recebeu resposta**;
- o pedido de simulação que **ficou sem retorno**;
- o pagamento combinado **por fora do canal oficial**.

As ferramentas que fazem isso (Gong, Chorus) são caras, em inglês e feitas para ligação, não
para WhatsApp. O Radar de Vendas é a versão aberta, brasileira e gratuita.

## Como funciona

```
Export do WhatsApp / API / webhook
        │
        ▼
Transcrição local de áudios  →  Mascaramento de dados pessoais (regex + modelo próprio)
        │
        ▼
Análise em três camadas auditáveis
   1. regras do playbook do setor (YAML, sem programar)
   2. classificador próprio (roda em CPU)
   3. LLM gratuito com failover (Groq → Gemini → OpenRouter → Ollama local)
        │
        ▼
Alertas com evidência · nota 0–100 explicável · resumo · sugestão de próxima mensagem
        │
        ▼
Painel web · e-mail / Telegram / webhook · relatórios
```

Nenhum texto sai da sua máquina sem máscara. No modo local (Ollama), nada sai da máquina.

## Começando

Requisitos: [Docker](https://docs.docker.com/get-docker/) com Compose.

```bash
git clone https://github.com/Tavares03/radar-vendas.git
cd radar-vendas
docker compose up --build
```

- Painel: <http://localhost:3000>
- Documentação da API (OpenAPI): <http://localhost:3000/api/docs>

Para criar a sua empresa e o primeiro administrador, copie `.env.example` para `.env` e preencha
`RADAR_BOOTSTRAP_TENANT_NAME`, `RADAR_BOOTSTRAP_ADMIN_EMAIL` e `RADAR_BOOTSTRAP_ADMIN_PASSWORD`
antes de subir. Ou, com tudo no ar:

```bash
docker compose exec api radar create-tenant "Minha Empresa"
docker compose exec api radar create-user minha-empresa voce@empresa.com.br --name "Você"
```

### Enviando conversas

No WhatsApp, abra a conversa → **Mais** → **Exportar conversa** (com ou sem mídia). Envie o
`.zip` ou o `.txt` pelo painel, ou pela API:

```bash
# um ou vários arquivos de uma vez
curl -X POST http://localhost:3000/api/v1/imports \
  -H "Authorization: Bearer $RADAR_TOKEN" \
  -F "files=@Conversa do WhatsApp com Cliente.zip"
```

O Radar reconhece exports de Android e iPhone, em português e inglês; transcreve os áudios
localmente (faster-whisper); identifica quem é o vendedor pelo cadastro, pelo título do export
ou pelo conteúdo — e avisa quando ficou em dúvida. Reenviar o mesmo arquivo não duplica nada, e
um export mais novo da mesma conversa só acrescenta as mensagens que faltam.

Sistemas próprios (CRM, N8N) podem mandar conversas em JSON para `POST /api/v1/conversations`.
Os tokens de integração são criados em `POST /api/v1/api-tokens`.

### Chaves de LLM (opcionais e gratuitas)

Sem nenhuma chave o sistema funciona com regras + classificador. Para resumo, sugestões e
análise mais fina, crie chaves gratuitas (não pedem cartão) e coloque no `.env`:

| Provedor | Onde criar | Variável |
|---|---|---|
| Groq | <https://console.groq.com/keys> | `GROQ_API_KEY` |
| Google Gemini | <https://aistudio.google.com/apikey> | `GEMINI_API_KEY` |
| OpenRouter | <https://openrouter.ai/keys> | `OPENROUTER_API_KEY` |

Para rodar **100% local**: `docker compose --profile local up` e `RADAR_LLM_MODE=local`.

## Desenvolvimento

Requisitos: Python 3.12, [uv](https://docs.astral.sh/uv/), Node 24.

```bash
uv sync --all-packages            # instala backend, synthetic, evals e ferramentas de dev
uv run pytest                     # testes (SQLite em memória, sem serviços)
uv run ruff check . && uv run ruff format --check .
uv run mypy backend/src synthetic/src evals/src

# API em modo leve (SQLite, fila na própria API)
uv run radar init-db
uv run uvicorn --factory radar.api.app:create_app --reload

# Painel
cd frontend && npm install && npm run dev
```

Para rodar os testes também em PostgreSQL (como a CI faz):

```bash
docker compose up -d db
RADAR_TEST_DATABASE_URL=postgresql+psycopg://radar:radar@127.0.0.1:5433/radar_test uv run pytest
```

(crie o banco `radar_test` uma vez: `docker compose exec db createdb -U radar radar_test`)

## Estrutura

| Pasta | O que tem |
|---|---|
| [`backend/`](backend) | pacote `radar`: API FastAPI, worker, e toda a lógica de análise |
| [`frontend/`](frontend) | painel em Next.js |
| [`synthetic/`](synthetic) | gerador de conversas sintéticas anotadas |
| [`training/`](training) | treino e avaliação dos modelos próprios |
| [`evals/`](evals) | avaliação do sistema inteiro |
| [`playbooks/`](playbooks) | regras por setor, em YAML |
| [`docs/`](docs) | plano, decisões, LGPD, guias |

## Documentação

- [Plano e status](docs/PLANO.md)
- [Registro de decisões](docs/DECISOES.md)
- [LGPD e privacidade](docs/LGPD.md)
- [Dados sintéticos](docs/DADOS-SINTETICOS.md)
- [Como contribuir](CONTRIBUTING.md)
- [Política de segurança](SECURITY.md)

## Privacidade (LGPD)

- **Máscara antes de tudo:** CPF, CNPJ, RG, telefone, e-mail, endereço, CEP, PIX, conta e
  cartão, placa e nomes viram `[CPF]`, `[TELEFONE]`… antes de qualquer análise. O painel mostra o
  texto mascarado; o original fica cifrado e só aparece com "revelar", auditado.
- **Retenção configurável:** texto original e áudios são apagados depois de X dias (padrão: 90 e
  30), pelo agendador ou por `radar retention-run`.
- **Direitos do titular:** localizar, exportar (JSON) e excluir os dados de uma pessoa pelo nome,
  telefone, CPF ou e-mail — sem que o banco guarde esses identificadores em claro.

```bash
curl -X POST http://localhost:3000/api/v1/privacy/subjects/search \
  -H "Authorization: Bearer $RADAR_TOKEN" -H "Content-Type: application/json" \
  -d '{"identifiers": ["529.982.247-25"]}'
```

Detalhes, bases legais e um checklist para quem vai usar: [docs/LGPD.md](docs/LGPD.md).

Todos os dados de exemplo, teste e treino deste repositório são **sintéticos**, gerados pelo
[`radar-synth`](docs/DADOS-SINTETICOS.md) (`uv run radar-synth sample --out conversa.zip` gera um
export pronto para importar). Não envie
conversas reais em issues ou pull requests.

## Licença

Código e modelos: [Apache-2.0](LICENSE). Dataset sintético: CC BY 4.0.
