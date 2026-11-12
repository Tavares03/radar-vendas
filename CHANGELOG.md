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
