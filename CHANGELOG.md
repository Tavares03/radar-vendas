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

### Corrigido
- Testes em SQLite rodavam com as chaves estrangeiras desligadas (`ON DELETE CASCADE` ignorado).
- Detector de dados pessoais: complemento "ap 41" no endereço, CNPJ alfanumérico sem formatação
  com contexto e chave PIX citada mais longe da palavra "pix".
