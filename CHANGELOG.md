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
