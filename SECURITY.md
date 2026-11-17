# Política de segurança

O Radar de Vendas processa conversas de clientes. Levamos falhas de segurança e de privacidade a
sério.

## Como relatar

**Não abra uma issue pública.** Use o
[relato privado de vulnerabilidades do GitHub](https://github.com/Tavares03/radar-vendas/security/advisories/new).

Inclua, se possível: o que acontece, como reproduzir (com dados **sintéticos**), o impacto e a
versão ou commit.

Você recebe uma resposta em até 7 dias. Correções críticas saem numa versão de correção e o
relato é creditado no `CHANGELOG.md`, se você quiser.

## O que é considerado vulnerabilidade

- acesso a dados de outra empresa (quebra de isolamento entre tenants);
- dado pessoal enviado a um LLM externo sem máscara, ou qualquer envio no modo local;
- escalada de papel (vendedor lendo conversa de outro vendedor, por exemplo);
- execução de código, leitura de arquivo ou SSRF por upload, webhook ou playbook;
- texto de conversa conseguindo alterar a análise como se fosse instrução (prompt injection)
  de forma a esconder um alerta crítico;
- vazamento de segredo em log, resposta de API ou imagem Docker.

## Boas práticas para quem instala

- defina `RADAR_SECRET_KEY` (32+ caracteres) e `POSTGRES_PASSWORD` próprios;
- use `RADAR_ENVIRONMENT=prod` e `RADAR_COOKIE_SECURE=true` atrás de HTTPS;
- não exponha as portas do banco, da API e da Evolution API diretamente à internet — só o painel;
- com o WhatsApp conectado, defina um `EVOLUTION_API_KEY` próprio;
- mantenha `RADAR_ALLOW_SIGNUP=false` se a instalação é de uma empresa só;
- revise a política de retenção em Configurações → Privacidade.
