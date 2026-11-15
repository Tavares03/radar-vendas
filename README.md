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

![Visão geral do painel: o resumo do período numa frase, os alertas críticos com o trecho marcado, a nota média por semana e a equipe](docs/img/visao-geral.png)

| Conversa com a evidência marcada | Evolução de cada vendedor |
|---|---|
| ![Conversa no estilo do WhatsApp com o trecho do alerta marcado, dados pessoais em tarja e a nota explicada ao lado](docs/img/conversa.png) | ![Página de um vendedor: evolução semanal, critérios da nota, objeções e alertas em aberto](docs/img/vendedor.png) |

As telas acima são da empresa de demonstração, com conversas 100% sintéticas.

> **Estado:** em construção, fase por fase. Importação, privacidade, análise, painel e modelos
> próprios já funcionam; o que falta está em [O que já funciona e o que vem](#o-que-já-funciona-e-o-que-vem).

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
Export do WhatsApp (.zip ou .txt) / API
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
Painel web      (em breve: avisos por e-mail, Telegram e webhook, e relatórios)
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

### Experimentar com dados de demonstração

Na primeira subida, com o banco vazio, o Radar carrega sozinho uma empresa de demonstração: a
"Plano Certo Consórcios", uma equipe fictícia de cinco vendedores com 45 conversas das últimas
oito semanas, analisadas em segundo plano. Os logins são `admin@demo.radar`, `gestor@demo.radar`
e `vendedor@demo.radar` (entre com cada um para ver o que cada papel enxerga). A senha é sorteada
e aparece uma vez no log da API:

```bash
docker compose logs api | grep demonstracao_criada
```

Para escolher a senha, defina `RADAR_DEMO_PASSWORD` (10 caracteres ou mais) no `.env` antes de
subir. Para não carregar a demonstração, `RADAR_SEED_DEMO=false`. Ela nunca é criada com
`RADAR_ENVIRONMENT=prod`, nem quando você configura o seu próprio administrador. Numa instalação
que já tem usuários, dá para carregá-la à mão:

```bash
docker compose exec api radar seed-demo
```

Todas as pessoas e empresas das conversas são inventadas, e as datas acompanham o dia da carga.

### O painel

| Página | Para quê |
|---|---|
| Visão geral | o que pede atenção agora: alertas críticos com o trecho, nota média, tendência das últimas 8 semanas e a equipe da pior para a melhor nota |
| Alertas | fila com filtros (severidade, status, tipo, vendedor); revisar, marcar falso positivo, atribuir responsável e anotar sem sair da lista |
| Conversas | importar exports e abrir cada conversa no estilo do WhatsApp, com o trecho de cada alerta marcado na cor da severidade e a nota explicada ao lado |
| Vendedores | nota, evolução semanal, objeções que mais custam, alertas em aberto e pontos a melhorar de cada pessoa |
| Playbooks | ver, editar e testar as regras do setor antes de salvar |
| Configurações | fuso, horário comercial, tempo de resposta esperado, retenção de dados e usuários |

Dado pessoal aparece sempre como tarja (`[CPF]`, `[TELEFONE]`…). Quem tem permissão pode revelar
o texto original de uma conversa, e isso fica na trilha de auditoria. O vendedor vê só as
próprias conversas e alertas.

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

Cada conversa importada é mascarada e analisada automaticamente. O resultado sai em
`GET /api/v1/conversations/{id}/analysis` (nota com critérios explicados, resumo, sugestão de
próxima mensagem e alertas com o trecho exato) e os alertas de todas as conversas ficam na fila
`GET /api/v1/alerts`, onde o gestor marca falso positivo, atribui responsável e anota. O que é
risco em cada setor está nos [playbooks](docs/PLAYBOOKS.md), editáveis sem programar.

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

## Modelos próprios

Dois modelos ajustados sobre o [BERTimbau](https://huggingface.co/neuralmind/bert-base-portuguese-cased),
treinados **só com dados sintéticos** e servidos em ONNX int8 na CPU (cerca de 8 ms por mensagem,
110 MB cada, sem PyTorch em produção):

| Modelo | O que faz | Resultado que importa (conjunto de teste) |
|---|---|---|
| `pii-ner-ptbr` | acha CPF, CNPJ, RG, telefone, e-mail, endereço, CEP, PIX, conta, placa e nomes | com o modelo, **100%** das entidades do teste ficam inteiras debaixo de máscara; só com regex, 92,6%. No conjunto de casos difíceis, 100% contra 60% |
| `sales-intent-ptbr` | marca riscos do vendedor, objeções, sinal de compra e pedidos do cliente | soma-se às regras dos playbooks: no conjunto de casos difíceis, a revocação sobe de 67% para 75% com precisão de 90%. Só aponta os rótulos em que acerta pelo menos 70% na validação |

O teste é sintético como o treino (com famílias de template que o treino nunca viu), então mede
generalização entre templates, não o mundo real; os relatórios completos, com matriz de
confusão, baselines e limitações, estão em [`training/reports/`](training/reports) e o passo a
passo em [docs/TREINAMENTO.md](docs/TREINAMENTO.md). Os modelos ainda não foram publicados no
Hugging Face: `scripts/publish_hf.py` publica com um comando quando houver um token.

## Desenvolvimento

Requisitos: Python 3.12, [uv](https://docs.astral.sh/uv/), Node 24.

```bash
uv sync --all-packages            # instala backend, synthetic, evals e ferramentas de dev
uv run pytest                     # testes (SQLite em memória, sem serviços)
uv run ruff check . && uv run ruff format --check .
uv run mypy backend/src synthetic/src evals/src training/src

# API em modo leve (SQLite, fila na própria API)
uv run radar init-db
uv run uvicorn --factory radar.api.app:create_app --reload

# Painel (o proxy /api aponta para http://127.0.0.1:8000)
cd frontend && npm install && npm run dev
npm run lint && npm run typecheck && npm test
```

Ao mudar um endpoint, regenere o contrato que o painel usa (um teste compara os dois):

```bash
uv run python scripts/export_openapi.py && (cd frontend && npm run api:types)
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
| [`frontend/`](frontend) | painel em Next.js ([como está organizado](frontend/README.md)) |
| [`synthetic/`](synthetic) | gerador de conversas sintéticas anotadas |
| [`training/`](training) | treino e avaliação dos modelos próprios |
| [`evals/`](evals) | avaliação do sistema inteiro |
| [`playbooks/`](playbooks) | regras por setor, em YAML |
| [`docs/`](docs) | plano, decisões, LGPD, guias |

## O que já funciona e o que vem

| | Estado |
|---|---|
| Importar exports do WhatsApp (Android e iPhone, PT-BR e EN), em lote e pela API | pronto |
| Transcrição local de áudios (faster-whisper) | pronto |
| Máscara de dados pessoais (regex, validadores e modelo próprio), texto original cifrado, retenção, auditoria e direitos do titular | pronto |
| Análise em camadas: regras do playbook, classificador próprio, métricas de tempo e LLM gratuito com failover | pronto |
| Playbooks de consórcio, seguros, imobiliária, clínica e genérico, editáveis e testáveis pelo painel | pronto |
| Painel: visão geral, fila de alertas, conversa com evidências, vendedores, playbooks, configurações | pronto |
| Modelos próprios treinados e avaliados (`pii-ner-ptbr`, `sales-intent-ptbr`), servidos em ONNX na CPU | pronto, ainda não publicados no Hugging Face |
| Demo pública no Hugging Face Spaces e avaliação do sistema inteiro na CI | a fazer |
| Alertas por e-mail, Telegram e webhook; webhooks de saída; exemplo para N8N; espelho do WhatsApp Cloud API e da Evolution API | a fazer |
| Coach do vendedor, biblioteca de boas respostas, insights da equipe, busca em linguagem natural e relatórios em PDF | a fazer |

O plano completo, fase por fase, está em [docs/PLANO.md](docs/PLANO.md).

## Documentação

- [Plano e status](docs/PLANO.md)
- [Registro de decisões](docs/DECISOES.md)
- [LGPD e privacidade](docs/LGPD.md)
- [Dados sintéticos](docs/DADOS-SINTETICOS.md)
- [Como escrever um playbook](docs/PLAYBOOKS.md)
- [Modelos próprios: treino, avaliação e publicação](docs/TREINAMENTO.md)
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
