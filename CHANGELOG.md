# Changelog

Todas as mudanças relevantes deste projeto ficam registradas aqui.
O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa
[versionamento semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
- Fundação do projeto: monorepo com uv workspace, pacote `radar`, API FastAPI, worker RQ sobre
  Valkey, PostgreSQL 17 + pgvector, painel Next.js e Docker Compose que sobe tudo com um comando.
- Autenticação por sessão (JWT em cookie httpOnly) e por token de API com escopos; papéis
  `admin`, `gestor`, `vendedor` e `auditor` com matriz de permissões.
- Isolamento automático entre empresas em todas as consultas e escritas.
- Trilha de auditoria, limite de requisições, cabeçalhos de segurança, métricas Prometheus e
  logs estruturados com `request_id`.
- CLI `radar` (criar empresa e usuário, bootstrap, worker, agendador).
- CI no GitHub Actions: lint, tipos, testes em SQLite e PostgreSQL, migrations e imagens Docker.
- Ingestão: parser do export do WhatsApp (Android e iOS, PT-BR e EN, mensagens multilinha, mídia
  omitida, anexos, mensagens apagadas e editadas, avisos de sistema) com inferência da ordem
  dia/mês pelo arquivo inteiro.
- Abertura segura de zips (zip bomb, path traversal, links simbólicos, senha, limites de tamanho)
  e limite de corpo por requisição.
- Identificação de vendedor e cliente pelo cadastro, pelo título do export ou pelo conteúdo, com
  nível de confiança e correção pelo painel.
- `POST /api/v1/imports` (upload único ou em lote) e `POST /api/v1/conversations` (JSON), ambos
  idempotentes; listagem, leitura, correção, reprocessamento e exclusão de conversas.
- Transcrição local de áudios com faster-whisper (`.opus`, `.ogg`, `.m4a`, `.mp3`).
- Texto bruto, nome do cliente e nome do arquivo cifrados em repouso; leitura mascarada por
  padrão e "revelar" auditado.
- Privacidade: detecção de dados pessoais em PT-BR (CPF, CNPJ alfanumérico, RG, telefone,
  e-mail, endereço, CEP, PIX, conta bancária e cartão, placa, nomes) por regex, validadores e
  contexto, mais os nomes dos participantes do export; detector em camadas pronto para o NER.
- Etapa de privacidade no pipeline: toda mensagem (inclusive áudio transcrito) é mascarada antes
  de qualquer análise; trava `ensure_masked` para texto que sai da máquina.
- Índice de titulares por HMAC e `POST /api/v1/privacy/subjects/search|export|delete` para
  atender os direitos de acesso, portabilidade e eliminação (LGPD, art. 18).
- Política de retenção por empresa (texto original, áudios, conversas inteiras): agendador a
  cada 6 horas, `radar retention-run [--dry-run]` e `GET|POST /api/v1/privacy/retention`.
- `docs/LGPD.md`: bases legais, dados guardados, mascaramento, retenção, direitos do titular,
  controle de acesso e checklist para quem vai usar.
- Dados sintéticos (`radar-synth`): gerador de conversas de venda em PT-BR no formato do WhatsApp
  para consórcio, seguros, imobiliária, clínica e varejo, com perfis de vendedor e cliente,
  ruído de WhatsApp, áudios com transcrição, anotação por mensagem (riscos, objeções, intenção e
  dados pessoais com posição) e alertas esperados por conversa.
- Splits sem vazamento de template, manifesto versionado, conjunto de desafio curado, revisão por
  amostragem, pacote para o Hugging Face com dataset card, e ferramentas de paráfrase e conjunto
  fora de distribuição com LLM gratuito.
- Severidade padrão de cada tipo de alerta na taxonomia compartilhada.
- Playbooks em YAML para genérico, consórcio, seguros, imobiliária e clínica, com herança,
  validação explicada e motor de regras que ignora negação, citação e refutação.
- Análise em camadas (regras → classificador → métricas → LLM) com fusão auditável, grounding
  das evidências do LLM, detecção de tentativa de manipulação e nota explicável calculada.
- Camada de LLM com failover entre Groq, Gemini, OpenRouter e Ollama, retry, limite de taxa,
  circuit breaker, cache e saída estruturada com reparo; texto sem máscara nunca vai para nuvem.
- Tabelas `analyses`, `alerts`, `stage_metrics` e `playbooks`; etapa de análise no pipeline;
  `GET /api/v1/conversations/{id}/analysis`, fila `/api/v1/alerts` com revisão (status,
  responsável, nota) que sobrevive à reanálise e `/api/v1/playbooks` (listar, ver, salvar,
  excluir e testar regras).
- Painel web: visão geral, fila de alertas com revisão em linha, visualizador de conversa no
  estilo do WhatsApp com o trecho de cada alerta marcado na cor da severidade e a nota explicada
  ao lado, página por vendedor, editor e teste de playbooks e configurações da empresa. Dado
  pessoal aparece como tarja; revelar o original pede confirmação e fica auditado. Funciona no
  celular.
- `GET /api/v1/overview` e `GET /api/v1/sellers/{id}/performance` (nota média, tendência
  semanal, alertas por tipo, objeções por desfecho, critérios e pontos a melhorar).
- `GET /api/v1/alerts/assignees`: quem pode receber um alerta, para quem revisa sem gerir
  usuários. Cada alerta traz o texto mascarado da mensagem, para mostrar a evidência no contexto.
- `radar seed-demo`: empresa de demonstração com as conversas sintéticas de exemplo e usuários
  admin, gestor e vendedor.
- Cliente do painel tipado a partir do OpenAPI da API, com teste que impede o contrato de ficar
  desatualizado; testes de componente com Vitest e Testing Library.
- `desativar` no playbook também vale para divulgações obrigatórias herdadas.
- Modelos próprios: `pii-ner-ptbr` (NER de dados pessoais em PT-BR) e `sales-intent-ptbr`
  (classificador multirrótulo de mensagens), ajustados sobre o BERTimbau só com dados sintéticos e
  servidos em ONNX int8 na CPU, sem PyTorch em produção.
- Runtime `radar.ml`: o NER entra como camada do detector de dados pessoais (com janelas para
  texto longo) e o classificador como camada da análise; `RADAR_NER_MODEL` e
  `RADAR_CLASSIFIER_MODEL` aceitam `auto`, `off`, pasta ou id do Hugging Face; falha ao carregar
  deixa a camada de fora sem derrubar nada. Comando `radar models`.
- `radar-train` (extra `train`): comparação de encoders, treino com semente fixa e configuração
  versionada, exportação ONNX com quantização int8, limiares calibrados no modelo int8, avaliação
  pelo runtime de produção contra regex, regras dos playbooks, TF-IDF e LLM zero-shot, relatórios
  em `training/reports/` e model cards.
- `scripts/publish_hf.py`: publica o dataset e os modelos no Hugging Face (só com `--yes` e
  `HF_TOKEN`; sem isso, mostra o plano).
- `docs/TREINAMENTO.md`: como treinar, avaliar, usar e publicar os modelos.
- Quantização com conferência de qualidade: cada receita é medida na validação contra o fp32 e só
  entra se perder no máximo 0,01; a escolha e as medidas vão para o relatório. Se nenhuma passar,
  o runtime usa o fp32 (inclusive ao baixar do Hugging Face).
- Piso de precisão na calibração do classificador (`min_precision`, padrão 0,7): rótulo que não
  acerta o bastante na validação fica desligado em vez de gerar alerta falso. A precisão dos
  riscos apontados só pelo modelo no teste sobe de 57% para 91%.
- Demonstração nova: a "Plano Certo Consórcios", uma equipe fictícia de cinco vendedores com 45
  conversas em oito semanas (`data/samples/demo`, gerada por `radar-synth demo`), com as datas
  acompanhando o dia da carga e a equipe já cadastrada.
- `RADAR_SEED_DEMO=true` passa a carregar a demonstração na primeira subida, em segundo plano,
  quando o banco não tem usuários (nunca em produção). A senha vem de `RADAR_DEMO_PASSWORD` ou é
  sorteada e mostrada uma vez no log.
- Painel redesenhado: barra lateral e login com a marca do radar, tipografia nova, selo de nota
  com a mesma régua em todo o painel, visão geral que resume o período numa frase com os números
  marcados, gráfico semanal de verdade (linha, faixa de bom atendimento, semana com alerta
  crítico, dica ao passar o mouse e tabela para leitor de tela), conversa com as cores do
  WhatsApp, nota num arco, alertas mais graves primeiro e envio de arquivos arrastando para a
  página. Ícone próprio no navegador.
- Contador de alertas críticos em aberto na navegação.
- WhatsApp ao vivo (perfil `whatsapp` do Compose): cada vendedor conecta o próprio número por QR
  code, como no WhatsApp Web, via Evolution API 2.3.7 guardada no mesmo PostgreSQL. As mensagens
  chegam por webhook (grupos, status e canais ficam de fora), são transcritas e mascaradas em
  segundos, e a análise com LLM roda depois de uma pausa na conversa. Só lê: não envia nem marca
  como lido; não importa o histórico antigo. Página **WhatsApp** no painel com a recomendação de
  usar WhatsApp Business com número de trabalho; a gestão vê a equipe toda e quem saiu do ar.
- Remoção de conversa com aprovação: o vendedor pede (com motivo) e só a gestão aprova ou recusa;
  aprovar apaga a conversa e, se ela veio do WhatsApp conectado, para de capturar o contato.
  Mensagem apagada "para todos" no WhatsApp fica no Radar marcada como apagada (com aviso na
  conversa), e a edição guarda o texto original.

### Mudado
- O vendedor não troca mais o playbook da própria conversa (trocar por um mais brando fazia
  alertas sumirem); só a gestão.
- Docker Compose só com PostgreSQL: a fila de jobs passa a ser uma tabela do próprio banco
  (`RADAR_QUEUE_MODE=postgres`, com deduplicação, atraso, retentativas, timeout e recuperação de
  jobs de worker morto) e o Valkey sai do Compose. Usuário e senha do banco passam a ser
  `postgres`/`postgres`; na primeira subida são criados também os bancos `radar_test` e `n8n`, e
  o N8N opcional guarda os dados no PostgreSQL. O modo `rq` continua disponível.
- A tendência semanal da visão geral cobre sempre as oito semanas, qualquer que seja o período.
- Textos do painel sem "(s)": "1 objeção", "Atendeu 0 de 1 pedido", e a demora na resposta em
  horas e minutos ("9 h 21 min de horário comercial") em vez de minutos crus.

### Corrigido
- `RADAR_DEMO_PASSWORD` com menos de 10 caracteres (ex.: `123456`) fazia a demonstração não ser
  criada, só com um aviso no log. As contas da demonstração agora aceitam qualquer tamanho; as
  demais mantêm o mínimo de 10.
- LLM num lote de importação: 35 de 45 conversas da demonstração ficavam sem análise de LLM. O
  limite de taxa do próprio Radar contava como falha e pausava a Groq e o Gemini pelo circuit
  breaker; agora não conta, e com todos os provedores no limite o worker espera o primeiro que
  liberar (até 65 s, `RADAR_LLM_THROTTLE_WAIT_SECONDS`). Um 429 com `Retry-After` longo pausa só
  aquele provedor pelo prazo pedido; um curto é respeitado antes de tentar de novo.
- Groq com `openai/gpt-oss-120b`: o raciocínio padrão gastava ~1500 dos 1800 tokens de resposta e
  o JSON saía cortado (HTTP 400 `json_validate_failed`). Agora vai `reasoning_effort=low`
  (`RADAR_GROQ_REASONING_EFFORT`) e o teto de resposta é 2400 tokens (`RADAR_LLM_MAX_OUTPUT_TOKENS`).
- Resposta cortada no limite de tokens (`finish_reason=length`) era "consertada" e aceita como se
  estivesse completa, sem objeções e pedidos; agora é recusada e o próximo provedor é usado.
- Erros HTTP dos provedores agora trazem o motivo (`HTTP 400 (json_validate_failed)`,
  `HTTP 401 (invalid_api_key)`) no log e na análise, em vez de só o código.
- `RADAR_OLLAMA_BASE_URL` com `/v1` (como o `.env.example` indicava) virava `/v1/v1`.
- Chaves de API com espaço ou `\r` (arquivo salvo no Windows) viravam um cabeçalho inválido.
- Os testes com LLM real (`RADAR_RUN_NETWORK_TESTS=1`) eram pulados quando a chave vinha só do
  ambiente, como o próprio teste ensina: o `conftest.py` apagava as chaves.
- Testes em SQLite rodavam com as chaves estrangeiras desligadas (`ON DELETE CASCADE` ignorado).
- Detector de dados pessoais: complemento "ap 41" no endereço, CNPJ alfanumérico sem formatação
  com contexto e chave PIX citada mais longe da palavra "pix".
- Consórcio, seguros, imobiliária e clínica herdavam do genérico a divulgação de condições de
  compra do varejo (fidelidade, troca, frete) e perdiam pontos de transparência por ela.
- A justificativa de transparência listava os identificadores das divulgações em vez da
  descrição em português.
- O `pii-ner-ptbr` quantizado errava muito mais que o original (F1 no teste de 0,63 contra 0,94
  do fp32; telefone com 2% de F1), a ponto de "regex + modelo" ter F1 pior que a regex sozinha.
  Com a quantização por canal e faixa reduzida, o int8 fica em 0,94 no teste e a combinação que
  roda no Radar deixa 100% das entidades do teste debaixo de máscara (eram 96%).
- `RADAR_SEED_DEMO` era lida e ignorada: `docker compose up` terminava num painel sem dados.
- A data de referência da visão geral aparecia um dia antes no horário do Brasil.
- O painel dava erro de console em desenvolvimento ("segment was dropped") porque a casca só
  desenhava a página depois de carregar o usuário; agora a casca e a página aparecem juntas.
- No celular, a visão geral rolava para o lado por causa da tabela para leitor de tela do gráfico.
