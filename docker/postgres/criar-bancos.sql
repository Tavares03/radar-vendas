-- Roda uma única vez, na primeira subida do PostgreSQL (volume de dados vazio).
-- O banco principal, "radar", já é criado pela variável POSTGRES_DB do docker-compose.yml.

-- Testes do backend contra PostgreSQL (ver "Desenvolvimento" no README).
CREATE DATABASE radar_test;

-- Dados do N8N (perfil opcional: docker compose --profile n8n up).
CREATE DATABASE n8n;
