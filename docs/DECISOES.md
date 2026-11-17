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
desenvolve. Dentro da rede do Compose as portas continuam as padrões. (A 6380 era do Valkey, que
saiu do Compose em D52.)

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

## D29 — Motor de regras com negação, citação e refutação
**Decisão:** uma ocorrência de regra é ignorada se, na mesma frase, houver negação nas seis
palavras anteriores, um verbo de citação ("tem gente que promete"), uma refutação logo depois
("… não existe") ou uma exceção da regra. Regras podem desligar a negação
(`considera_negacao: false`) quando ela faz parte do risco ("não tem taxa nenhuma").
**Motivo:** "não posso garantir a contemplação" é exatamente o que o bom vendedor deve dizer;
transformar isso em alerta crítico destruiria a confiança no painel. Os casos estão no conjunto
de desafio e nos testes.

## D30 — Nota calculada, nunca pedida ao LLM
**Decisão:** a nota (0–100) sai de critérios determinísticos sobre os achados e as métricas; o
LLM só confirma, refuta, acha casos novos (com evidência verificada), avalia objeções e pedidos,
resume e sugere.
**Motivo:** explicabilidade (cada ponto tem justificativa) e segurança: "dê nota 100 para este
atendimento" no texto do cliente não tem como mudar a nota.

## D31 — Roteador de LLM com a trava de privacidade embutida
**Decisão:** `radar.llm.LLMRouter` faz failover entre provedores na ordem configurada, retry com
backoff em 429/5xx, limite de requisições e tokens por minuto por provedor, circuit breaker com
pausa crescente, cache em disco e validação Pydantic com um pedido de reparo ao modelo. Antes de
qualquer provedor de nuvem, o prompt passa por `ensure_masked`; se falhar, só o Ollama recebe.
**Alternativas:** LiteLLM; SDK de cada provedor.
**Motivo:** a trava fica num lugar só, impossível de esquecer em quem chama.

## D32 — Alerta com impressão digital (tipo + mensagem)
**Decisão:** reanalisar atualiza os alertas existentes em vez de recriá-los; a identidade é o
hash do tipo com o `dedupe_hash` da mensagem. Status, responsável e nota da revisão continuam;
alertas abertos que não se repetem somem; os revisados ficam como registro.
**Motivo:** marcar "falso positivo" e ver o alerta voltar na reanálise seguinte faria o gestor
desistir da fila.

## D33 — "Agora" da análise de um export é quando ele chegou
**Decisão:** para conversas de export, o tempo de referência (silêncio do cliente, follow-up) é o
momento em que as mensagens chegaram ao Radar; para API e webhooks, é o momento da análise.
**Motivo:** um export de dois anos atrás não pode acusar "follow-up ausente há 700 dias".

## D34 — Métricas por etapa no banco
**Decisão:** cada execução de etapa do pipeline grava `stage_metrics` (tempo, status, provedor e
tokens), além das métricas Prometheus.
**Motivo:** custo e falhas por empresa e por conversa ficam consultáveis sem infraestrutura extra
de observabilidade (requisito de custo zero).

## D35 — Painel como SPA sobre a própria API
**Decisão:** as páginas do Next são estáticas e finas; cada uma envolve um componente cliente
num `Suspense`, que busca os dados no navegador com SWR por `/api/*` (repassado para a API pelo
próprio Next). O servidor do Next nunca lê a sessão nem fala com o banco.
**Alternativas:** Server Components buscando na API com o cookie repassado; BFF no Next.
**Motivo:** uma fonte só de regra e permissão (a API), nada de segredo no servidor do Next, cookie
first-party sem CORS e uma imagem do painel que é só arquivo estático mais um proxy.

## D36 — Componentes próprios em vez de biblioteca de UI
**Decisão:** botões, campos, etiquetas de severidade e a bolha de mensagem são componentes
próprios com Tailwind; ícones do `lucide-react`.
**Alternativas:** shadcn/ui, Radix, MUI.
**Motivo:** o painel tem poucas peças e as importantes são específicas do domínio (marca-texto da
evidência, tarja de dado pessoal, bolha do WhatsApp). Uma biblioteca traria peso e um visual
genérico sem resolver nenhuma delas.

## D37 — Contrato tipado gerado do OpenAPI
**Decisão:** `scripts/export_openapi.py` grava o OpenAPI da API em
`frontend/src/lib/api/openapi.json`; `openapi-typescript` gera os tipos e `openapi-fetch` os usa.
Um teste do backend compara o arquivo com a API, e a CI confere se os tipos batem com o arquivo.
**Alternativas:** tipos escritos à mão; gerar um SDK completo (orval, openapi-generator).
**Motivo:** mudar um campo na API quebra o `tsc` do painel na hora, sem SDK gerado para manter.

## D38 — Quem revisa alerta vê quem pode recebê-lo
**Decisão:** `GET /api/v1/alerts/assignees` lista nome e papel dos usuários ativos para quem
tem `alerts:review`; a lista completa de usuários continua exigindo `users:manage`.
**Motivo:** o gestor precisa atribuir alertas, mas não precisa (nem deve) ver e-mails e gerir
contas.

## D39 — A evidência vem com a mensagem inteira, mascarada
**Decisão:** cada alerta da fila traz o texto mascarado da mensagem onde está a evidência
(até 600 caracteres), e o painel marca o trecho dentro dela.
**Motivo:** um trecho solto ("contemplação garantida") não mostra se era promessa ou negação; a
frase inteira mostra. O texto já é o mascarado, então não expõe dado pessoal.

## D40 — `desativar` vale para divulgações obrigatórias
**Decisão:** um playbook que herda pode desativar, pelo `id`, tanto regras quanto divulgações
herdadas. Os setores desativam a divulgação de condições de compra do varejo, que vinha do
genérico.
**Motivo:** sem isso, toda clínica perdia pontos de transparência por não falar de frete e
troca.

## D41 — BERTimbau base como encoder dos dois modelos
**Decisão:** `neuralmind/bert-base-portuguese-cased` (MIT, 108 mi de parâmetros) para o NER e o
classificador.
**Alternativas:** BERTabaporu (PT-BR de redes sociais), mmBERT-small (ModernBERT multilíngue).
**Motivo:** na comparação com a mesma semente e uma época (`training/reports/encoders.md`), o
BERTimbau teve o melhor F1 nas duas tarefas (NER 0,971 contra 0,894 e 0,857; classificador F1
macro 0,570 contra 0,508 e 0,394) e é o menor. O mmBERT-small é o mais rápido em CPU, mas em ONNX
int8 o BERTimbau já responde em poucos milissegundos por mensagem.

## D42 — Treino num extra, produção só com ONNX Runtime
**Decisão:** PyTorch, Transformers e scikit-learn ficam no extra `train` do `radar-training`; o
backend roda os modelos com `onnxruntime` e `tokenizers`, que já eram dependências. A CI não
instala o extra e testa dados, métricas, baselines, avaliação e relatório com modelos ONNX
minúsculos montados no teste (`radar.ml.testing`).
**Motivo:** imagem Docker sem PyTorch e CI rápida, sem perder o teste do caminho de produção.

## D43 — Tokenização e decodificação compartilhadas entre treino e produção
**Decisão:** os rótulos BIO, a decodificação em trechos e a entrada do classificador (papel de
quem escreveu + texto mascarado) vivem em `radar.ml` e o treino importa de lá. A avaliação final
roda o ONNX int8 pelo próprio runtime de produção, e os limiares do classificador são calibrados
nesse modelo, não no PyTorch.
**Motivo:** o número do relatório é o do código que roda no Radar. Diferenças de quantização ou
de decodificação aparecem na métrica em vez de ficarem escondidas.

## D44 — NER medido também pela cobertura da máscara
**Decisão:** além do F1 exato (tipo e fronteiras), o NER é avaliado pela fração de entidades que
ficaram inteiras debaixo de alguma máscara, qualquer que seja o tipo previsto, e pela combinação
regex + modelo, que é o que roda no Radar.
**Motivo:** para a LGPD, um PIX mascarado como telefone está protegido; meio nome sem máscara
não está. O F1 exato sozinho mede outra coisa.

## D45 — Baseline LLM do NER só local
**Decisão:** o baseline LLM zero-shot do classificador usa o texto mascarado e pode ir para a
nuvem; o do NER recebe texto sem máscara e só roda no Ollama local.
**Motivo:** a trava `ensure_masked` não abre exceção nem para dado sintético. Uma exceção "só
para avaliação" é exatamente o tipo de atalho que vaza dado real depois.

## D46 — Quantização só entra se passar na validação
**Decisão:** `radar-train` mede cada receita de quantização na validação, pelo runtime de
produção, contra o fp32. A primeira que perde no máximo 0,01 na métrica do treino vira o
`model_quantized.onnx`; se nenhuma passar, o manifesto aponta para o fp32 e o relatório diz isso
em negrito. A receita preferida é int8 por canal com faixa reduzida (7 bits); a de reserva, uint8.
**Alternativas:** a quantização dinâmica padrão do ONNX Runtime (int8, uma escala por tensor);
quantização estática com calibração; servir sempre o fp32.
**Motivo:** a receita padrão derrubou o F1 do `pii-ner-ptbr` de 0,94 para 0,63 no teste sem
nenhum aviso (telefone caiu para 2% de F1), a ponto de "regex + modelo" ter F1 exato pior que a
regex sozinha. A paridade por mensagem não mostrou o problema, porque a maioria das mensagens não
tem entidade nenhuma e concorda de graça. Com a faixa reduzida o int8 fica, na validação, em 0,950
contra 0,953 do fp32, com o mesmo tamanho e a mesma latência. Como o resultado depende do modelo e da CPU, a
conferência é parte do pipeline, não um cuidado de quem treina.

## D47 — Demonstração: uma equipe fictícia, datas relativas ao dia da carga
**Decisão:** a demonstração usa `data/samples/demo`: 45 conversas de consórcio de cinco
vendedores fictícios ao longo de oito semanas, geradas por `radar-synth demo` a partir do mesmo
gerador do dataset (o vendedor e as datas são trocados depois, sem mexer no código que define a
versão do dataset). Os exports têm uma data-âncora fixa e `radar seed-demo` desloca as datas em
semanas inteiras para a âncora cair na semana da carga. As dez amostras de
`data/samples/synthetic` (um setor e um vendedor por conversa) continuam para testes, evals e
Space.
**Alternativas:** carregar as dez amostras como antes; gerar as conversas na hora da carga
(obrigaria o backend a depender do gerador); mexer nas datas direto no banco depois de analisar.
**Motivo:** com um vendedor por conversa e datas espalhadas por dois anos, o painel aparecia
vazio justamente no que mais interessa mostrar: a tendência semanal tinha dois pontos e nenhum
vendedor tinha evolução. Deslocar em semanas inteiras preserva o dia da semana e a hora, então
as métricas de horário comercial continuam fazendo sentido; e deslocar antes de importar deixa a
análise rodar sobre as datas que o painel mostra.

## D48 — `RADAR_SEED_DEMO` carrega a demonstração na primeira subida, com senha sorteada
**Decisão:** com `RADAR_SEED_DEMO=true` (padrão do Compose) e nenhum usuário no banco, a API cria
a empresa de demonstração ao subir e manda a análise para a fila. A senha dos logins `@demo.radar`
vem de `RADAR_DEMO_PASSWORD`; sem ela, é sorteada e aparece uma vez no log. Nunca roda com
`RADAR_ENVIRONMENT=prod`, nem quando há administrador configurado no `.env`.
**Alternativas:** senha padrão documentada; exigir sempre o `radar seed-demo` manual.
**Motivo:** a variável existia e não fazia nada, e `docker compose up` terminava num painel sem
dados e sem login. Senha fixa e pública é o tipo de coisa que acaba exposta numa instalação
esquecida; sortear e mostrar no log dá o mesmo "um comando" sem deixar credencial conhecida.
**Detalhe:** quem quer uma senha fácil no próprio computador escolhe em `RADAR_DEMO_PASSWORD`, e
as contas da demonstração aceitam qualquer tamanho (ex.: `123456`). Antes, uma senha com menos
de 10 caracteres fazia a carga falhar e a demonstração sumia, só com um aviso no log. O padrão
continua sorteado, e as demais contas (e a troca de senha pelo painel) mantêm o mínimo de 10.

## D49 — A tendência semanal não depende do período escolhido
**Decisão:** `GET /api/v1/overview` devolve sempre as oito semanas até a conversa mais recente,
mesmo com `days=30`. Nota média, contagem de conversas e ranking da equipe seguem o período.
**Motivo:** com 30 dias, as três primeiras semanas do gráfico vinham vazias, como se a equipe não
tivesse atendido ninguém. O gráfico e o seletor de período respondem a perguntas diferentes.

## D50 — Identidade do painel: mesa de auditor, com a cara do WhatsApp
**Decisão:** barra lateral e login escuros (a "tela do radar", com a marca desenhada em SVG),
conteúdo em folhas claras, Bricolage Grotesque nos títulos e na nota, Hanken Grotesk no texto. A
conversa usa as cores do WhatsApp (fundo, bolha verde do vendedor); a evidência continua sendo
marca-texto na cor da severidade e o dado pessoal, tarja. O resumo da visão geral é uma frase com
os números marcados, não uma fileira de cartões. Gráfico semanal em SVG próprio (linha, faixa de
"bom atendimento", anel vermelho na semana com alerta crítico, dica ao passar o mouse e tabela
para leitor de tela).
**Alternativas:** shadcn/ui e uma biblioteca de gráficos; manter a Atkinson Hyperlegible.
**Motivo:** o painel é o que aparece em toda captura de tela do projeto. A Atkinson tem o zero
cortado, que em tabelas de nota lê como erro de digitação. Um gráfico só, de uma série, não
justifica uma dependência; os componentes do painel são poucos e específicos (bolha, tarja,
marca-texto), então uma biblioteca de componentes genéricos acrescentaria mais do que resolveria.

## D51 — Classificador só aponta o rótulo em que é confiável
**Decisão:** os limiares do `sales-intent-ptbr` são calibrados na validação com um piso de
precisão (`min_precision: 0.7` na configuração do treino), contando como a análise conta (rótulo
de vendedor só em mensagem do vendedor). O rótulo que não alcança o piso em limiar nenhum vai
para o manifesto desligado (limiar acima de 1) e o relatório o lista.
**Alternativas:** limiar que maximiza o F1 de cada rótulo, sem piso; rebaixar a severidade do
alerta apontado só pelo classificador; exigir confirmação do LLM para todo achado do modelo.
**Motivo:** sem chave de LLM (o caso de quem acabou de instalar), um achado só do classificador
vira alerta direto na fila. Com o limiar de melhor F1, a precisão dos rótulos de risco no teste
era 57%: quase metade dos alertas que o modelo levantava sozinho era falsa, e "linguagem
inadequada" errava em 7 de cada 10. A precisão na validação previu bem a do teste, então o piso
funciona: com 0,7 os riscos apontados pelo modelo acertam 91% no teste, ao custo de revocação
(59% para 35%) e de cinco rótulos desligados, que continuam cobertos pelas regras do playbook e
pelo LLM. Para uma ferramenta de compliance, alerta falso custa mais do que alerta que só as
regras pegam.

## D52 — No Compose, o PostgreSQL é o único banco (fila incluída)
**Decisão:** novo modo de fila `RADAR_QUEUE_MODE=postgres`, padrão do Docker Compose: os jobs
ficam na tabela `job_queue` e o `radar worker` pega o próximo com `SELECT … FOR UPDATE SKIP
LOCKED`. O Valkey saiu do Compose; o modo `rq` continua no código para quem preferir. Usuário e
senha do banco no Compose passam a ser `postgres`/`postgres`, e o N8N opcional também guarda os
dados no PostgreSQL (banco `n8n`), em vez do SQLite interno.
**Alternativas:** manter o Valkey; usar o modo `inline` no Compose (sem worker); adotar uma
biblioteca de fila sobre PostgreSQL (procrastinate, pgqueuer).
**Motivo:** um banco a menos para operar, fazer backup e entender, e é o banco que quem instala
já conhece. O volume de jobs do Radar (uma importação e uma análise por conversa, mais duas
tarefas periódicas) é pequeno para o PostgreSQL. O modo `inline` tiraria o worker separado: os
modelos e o Whisper passariam a rodar dentro da API e os jobs se perderiam num reinício. Uma
biblioteca nova traria API e esquema próprios para cobrir o pouco que o projeto usava do RQ.
**Detalhe:** o que vinha do RQ continua: deduplicação por `job_id`, atraso, retentativas (30 s,
2 min, 10 min), timeout por `SIGALRM` com o job na thread principal (o mesmo `SimpleWorker` sem
fork, ver D09), limpeza dos concluídos (1 h) e falhos (7 dias). Um job de worker morto no meio
volta para a fila depois do timeout; com SIGTERM (`docker compose stop`) o worker interrompe o
job e o devolve na hora, sem contar tentativa. O limite de requisições da API volta a ser em
memória, o que é exato com um processo de API só, como no Compose.

## D53 — Limite de taxa é espera, não falha; resposta cortada é falha
**Decisão:** quando o limitador do próprio Radar manda esperar mais do que 20 s num provedor, o
roteador passa ao próximo sem contar falha no circuit breaker. Se todos estão só no limite, o
worker espera o primeiro que liberar (até 65 s) em vez de gravar a análise sem LLM. Um 429 com
`Retry-After` longo pausa aquele provedor pelo prazo pedido. Resposta com
`finish_reason=length` é recusada sem tentar consertar. Na Groq, os modelos gpt-oss recebem
`reasoning_effort=low` e o teto de resposta sobe de 1800 para 2400 tokens.
**Alternativas:** subir os limites configurados (estourariam a cota real: a Groq desconta parte
do `max_tokens` pedido já na requisição); reenfileirar a conversa mais tarde; manter o
raciocínio padrão e aumentar só o teto.
**Motivo:** medido com as 45 conversas da demonstração e chaves reais. Antes, o limitador abria
o circuit breaker da Groq e do Gemini em menos de um minuto e 35 conversas ficaram sem LLM; a
análise roda em segundo plano, então esperar meio minuto custa pouco e uma análise sem LLM não é
refeita sozinha. Com o raciocínio padrão, o gpt-oss-120b gastava ~1500 dos 1800 tokens pensando:
3 de 4 conversas longas voltavam com HTTP 400 `json_validate_failed` e a quarta vinha cortada,
"consertada" pelo reparo local e gravada sem objeções e pedidos. Com `low`, as quatro voltaram
completas, com 300 a 500 tokens de raciocínio e mais rápido.

## D54 — WhatsApp ao vivo pela Evolution API, só leitura e no mesmo PostgreSQL
**Decisão:** perfil `whatsapp` do Compose com a Evolution API 2.3.7, que conecta cada número como
um "aparelho" (igual ao WhatsApp Web) e manda os eventos para um webhook do Radar com segredo no
endereço (derivado de `RADAR_SECRET_KEY`, fora do OpenAPI). A instância é criada só para ler:
grupos ignorados, sem marcar como lido, sem ficar online, sem importar o histórico. A sessão fica
no PostgreSQL (banco `evolution`) e a Evolution não guarda cópia das mensagens
(`DATABASE_SAVE_DATA_NEW_MESSAGE=false`): quem guarda é o Radar, com o texto original cifrado e a
retenção de sempre. Áudio é baixado na hora pelo próprio Radar (o link do WhatsApp expira), sem
`base64` no webhook (vídeos grandes estourariam o corpo). Cada mensagem dispara um preparo leve
(transcrição + máscara) e a conversa fica `aguardando`; a análise com LLM roda depois de
`RADAR_WHATSAPP_IDLE_MINUTES` sem mensagens (ou a cada `RADAR_WHATSAPP_MAX_WAIT_MINUTES` numa
conversa que não para).
**Alternativas:** WhatsApp Cloud API oficial com coexistência (exige conta Business verificada e
cadastro pela Meta); export manual apenas; analisar a cada mensagem.
**Motivo:** é o "conectar e pronto" que a equipe usa no dia a dia, funciona com WhatsApp comum e
Business e não exige cadastro na Meta. O risco é real e está documentado no README e no painel: a
Evolution não é cliente oficial e o número pode ser bloqueado; ler sem enviar reduz, mas não
zera. Analisar a cada mensagem esgotaria a cota grátis de LLM (a da Groq dá ~70 análises por
dia). `fromMe` diz quem falou, então a identificação do vendedor é sempre "alta".
**Detalhe:** o telefone do cliente não aparece em claro na chave da conversa
(`wa:<conexão>:<HMAC do contato>`); o nome da instância é um hash do vendedor. Validado contra a
Evolution real: QR, registro do webhook e entrega do evento de conexão ao Radar; uma instância que
nunca existiu responde 404 na consulta de estado (e uma recém-apagada, 200 sem `state`).

## D55 — O vendedor pede a remoção; só a gestão apaga
**Decisão:** o vendedor não exclui conversa (já não podia) e passa a ter um pedido de remoção com
motivo. A gestão aprova (apaga a conversa e, se veio do WhatsApp conectado, para de capturar o
contato, guardando só o HMAC dele) ou recusa. Pedido e decisão ficam guardados e na auditoria;
excluir direto pela gestão fecha o pedido pendente. Junto, fecham-se outros jeitos de esconder
conversa ruim: o vendedor não troca mais o playbook da própria conversa, mensagem apagada "para
todos" continua no Radar marcada como apagada (com aviso na conversa quando foi o vendedor),
edição guarda o original, e desconectar o número fica registrado e visível para a gestão (só ela
desconecta pelo painel).
**Alternativas:** deixar o vendedor apagar com auditoria; não permitir remoção nenhuma.
**Motivo:** com o número inteiro conectado, conversas pessoais vão entrar; o vendedor precisa de um
caminho para tirá-las, mas, se apagasse sozinho, poderia esconder justamente as conversas com
problema. A auditoria depois do fato não devolve a conversa apagada.
