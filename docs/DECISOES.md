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

## D14 — Ingestão idempotente por hash de mensagem
**Decisão:** toda entrada (export, API, webhook) passa por `ingest_conversation`. Cada mensagem
tem um hash (hora + autor + tipo + texto + ordem de ocorrência). Reenviar o mesmo arquivo devolve
a importação original; um export mais novo da mesma conversa só acrescenta o que falta.
**Detalhe importante:** dois exports só são tratados como a mesma conversa se tiverem os mesmos
participantes **e** pelo menos uma mensagem em comum. Só o nome não basta: dois clientes
"Maria" do mesmo vendedor não podem ser fundidos.

## D15 — Do zip, só o áudio vai para o disco
**Decisão:** fotos, vídeos e documentos do export não são extraídos nem guardados; só os áudios,
porque precisam ser transcritos — e eles são apagados pela política de retenção de mídia.
O arquivo enviado é removido assim que é processado.
**Motivo:** minimização (LGPD) e menos superfície de ataque: nada do zip é gravado com o nome
que veio nele.

## D16 — Áudio decodificado com PyAV, fora do faster-whisper
**Decisão:** o projeto decodifica o áudio (PyAV → mono 16 kHz) e entrega o vetor ao modelo.
**Motivo:** não exige ffmpeg instalado, permite recusar áudios longos antes de carregá-los
inteiros e não depende da função de decodificação interna do faster-whisper, que quebrou com
uma versão mais nova do PyAV durante o desenvolvimento.

## D17 — Datas ambíguas do export nunca são resolvidas em silêncio
**Decisão:** a ordem dia/mês é inferida pelo arquivo inteiro (valores acima de 12, inversões de
ordem cronológica, amplitude do período). Se continuar ambígua, vale dia/mês (ou mês/dia quando o
arquivo usa AM/PM) e a conversa recebe um aviso visível.

## D18 — Texto sem máscara não aparece
**Decisão:** a API devolve o texto mascarado. Antes de a etapa de privacidade rodar, a mensagem
vem com `text_available: false` em vez do texto original. O original (e o áudio) só sai com
`reveal=true`, para papéis autorizados pela empresa, e cada acesso fica na trilha de auditoria.
Tokens de API nunca recebem dado pessoal em claro.

## D19 — Detecção de dados pessoais em camadas, mascarando na dúvida
**Decisão:** regex + validadores + contexto → nomes dos participantes do export → NER próprio
(fase 7). Trechos sobrepostos viram um só (a união), e vence o mais longo; no empate, o tipo mais
específico (CPF antes de RG, por exemplo).
**Regra de desempate entre precisão e cobertura:** número *formatado* como CPF, CNPJ ou telefone
é mascarado mesmo com dígito verificador errado (erro de digitação continua sendo dado pessoal);
número *sem formatação* só é mascarado se passar no validador ou se o contexto disser o que ele é.
**Motivo:** o custo de vazar um CPF é muito maior que o de esconder um número inofensivo; mas
mascarar todo número corrido destruiria valores, prazos e protocolos que a análise precisa ler.

## D20 — Marcadores com o nome do tipo (`[CPF]`, `[NOME_PESSOA]`)
**Alternativas:** pseudônimos numerados (`[NOME_1]`); dados falsos no lugar (substituição).
**Motivo:** inequívoco para o LLM e para quem lê, igual à taxonomia do NER e do dataset, e não
cria a ilusão de um dado real. Os trechos (`pii_spans`) apontam para os marcadores no texto
mascarado, e o painel estiliza a partir deles.

## D21 — Índice de titulares por HMAC (`pii_index`)
**Decisão:** cada identificador encontrado (e cada cliente participante) vira uma linha com o
HMAC-SHA256 por empresa, o tipo e a conversa/mensagem. Localizar, exportar e excluir os dados de
um titular é uma busca pelo HMAC dos identificadores informados.
**Alternativas:** busca por texto no original cifrado (impossível sem decifrar tudo); guardar
os identificadores em claro (contradiz a minimização).
**Detalhe:** a relação com a conversa é `participante` (é o cliente) ou `mencionado` (um dado
dele aparece na conversa de outra pessoa). Na exclusão, a conversa do participante some
inteira; na conversa de terceiro, só o texto original das mensagens que o mencionam.

## D22 — Retenção contada a partir do recebimento, mascarando antes de apagar
**Decisão:** os prazos contam de `created_at` (quando o Radar recebeu o dado), não da data da
mensagem. Mensagem sem máscara é mascarada antes de perder o original. Nomes dos participantes
(cifrados) ficam até a retenção da conversa ou o pedido do titular.
**Motivo:** importar um export de dois anos atrás não pode apagar o original no mesmo instante;
e nenhuma mensagem pode virar um buraco sem texto por causa da ordem das etapas.

## D23 — Trava de saída (`ensure_masked`)
**Decisão:** todo texto que vai sair da máquina (LLM em nuvem, webhooks) passa de novo pela
detecção estruturada; se ainda tiver CPF, telefone, e-mail etc., o envio é recusado e o erro só
cita os tipos.
**Motivo:** defesa em profundidade contra um bug que mande `text_raw` no lugar de `text_masked`.

## D24 — Testes em SQLite com chaves estrangeiras ligadas
**Decisão:** a limpeza entre testes apaga as tabelas em ordem reversa de dependência, sem
desligar as chaves estrangeiras.
**Motivo:** o `PRAGMA foreign_keys=ON` executado dentro da transação era ignorado pelo SQLite, e
o `ON DELETE CASCADE` deixava de valer nos testes — um teste podia passar no SQLite e falhar no
PostgreSQL. Um teste garante que as chaves continuam ligadas.

## D25 — Dataset por templates com anotação por construção (e LLM só para variedade)
**Decisão:** as conversas nascem de roteiros e bancos de templates; rótulos e posições de dados
pessoais vêm do ato e do slot que geraram cada trecho. LLM gratuito entra só para paráfrases
(validadas) e para um conjunto fora de distribuição.
**Alternativas:** pedir ao LLM conversas já rotuladas (rótulos ruidosos, sem posições exatas,
não reprodutível); anotar depois com heurística (circular: o modelo aprenderia a heurística).
**Motivo:** rótulos confiáveis, reprodutibilidade por semente e custo zero; o LLM aumenta a
variedade sem ser a fonte da verdade.

## D26 — Splits por família de template, separados por grupo
**Decisão:** famílias inteiras vão para treino ou para a parte reservada; a separação é feita por
(arquivo de origem, ato), e cada tipo de dado pessoal tem um ato próprio com 3+ famílias.
**Motivo:** sem isso o teste mediria memorização. A versão inicial ligava cada tipo de dado
pessoal a uma única família, e tipos inteiros (endereço, RG, CNPJ) sumiam do treino — um teste
agora garante os 11 tipos nos três splits.

## D27 — Severidade padrão na taxonomia
**Decisão:** `DEFAULT_SEVERITY` em `radar.taxonomy` é a severidade de cada tipo de alerta quando
o playbook não define outra, e a verdade de referência do dataset e dos evals.
**Motivo:** gerador, playbooks e evals precisam falar a mesma severidade.

## D28 — Transcrição que acompanha o áudio no zip
**Decisão:** os áudios sintéticos são arquivos falsos com a transcrição ao lado
(`<áudio>.txt`), que o Radar já usa no lugar do Whisper.
**Motivo:** a demo e os testes exercitam o caminho de áudio inteiro sem TTS nem modelo de fala.
Os dois `.opus` de `data/samples/audio` continuam cobrindo a transcrição real.
