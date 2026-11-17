# Radar de Vendas e a LGPD

Este documento explica como o Radar de Vendas trata dados pessoais, o que ele faz para proteger
esses dados e o que **a empresa que o instala** precisa fazer para usá-lo dentro da Lei Geral de
Proteção de Dados (Lei 13.709/2018).

> **Isto não é parecer jurídico.** É a documentação técnica de um software. Cada empresa precisa
> avaliar o próprio caso com o seu encarregado (DPO) ou assessoria jurídica.

## Sumário

1. [Quem é quem](#1-quem-é-quem)
2. [Bases legais](#2-bases-legais)
3. [Que dados o Radar guarda e como](#3-que-dados-o-radar-guarda-e-como)
4. [Mascaramento de dados pessoais](#4-mascaramento-de-dados-pessoais)
5. [LLMs: nuvem, local ou desligado](#5-llms-nuvem-local-ou-desligado)
6. [Retenção](#6-retenção)
7. [Direitos do titular](#7-direitos-do-titular)
8. [Controle de acesso e auditoria](#8-controle-de-acesso-e-auditoria)
9. [Segurança](#9-segurança)
10. [WhatsApp conectado (ao vivo)](#10-whatsapp-conectado-ao-vivo)
11. [Checklist para quem vai usar](#11-checklist-para-quem-vai-usar)

---

## 1. Quem é quem

| Papel na LGPD | No uso do Radar |
|---|---|
| **Controlador** | A empresa que instala o Radar e decide analisar as conversas da equipe. |
| **Titulares** | Os clientes que conversam com a empresa e os próprios vendedores. |
| **Operador** | Quem hospeda a instalação para a empresa, se não for ela mesma. |
| **Suboperadores** | Os provedores de LLM em nuvem, quando o modo `cloud` está ligado (seção 5). |

O Radar é software livre e roda na infraestrutura de quem o instala (*self-hosted*). O projeto
não recebe nenhum dado das instalações.

## 2. Bases legais

A base legal é escolha do controlador. As mais comuns para este uso:

- **Procedimentos preliminares e execução de contrato** (art. 7º, V): a conversa de venda é o
  próprio pré-contrato com o cliente.
- **Legítimo interesse** (art. 7º, IX e art. 10): supervisionar a qualidade do atendimento e
  prevenir promessas indevidas. Exige um teste de balanceamento documentado, transparência com
  clientes e vendedores e a possibilidade de oposição.
- **Cumprimento de obrigação legal ou regulatória** (art. 7º, II): setores regulados (consórcio,
  seguros) têm deveres de informação e de registro que a análise ajuda a cumprir.

**Vendedores também são titulares.** Informe a equipe, por escrito, que as conversas comerciais
são analisadas, com que finalidade e quem vê os resultados.

**Dados sensíveis** (art. 11): em clínicas e na área de saúde, conversas podem conter dados de
saúde. O Radar não tem um detector específico para eles. Nesse setor, use o modo local
(`RADAR_LLM_MODE=local`), restrinja quem pode revelar o texto original e avalie a base legal do
art. 11 com cuidado.

## 3. Que dados o Radar guarda e como

| Dado | Onde fica | Proteção | Quando some |
|---|---|---|---|
| Texto original das mensagens (e transcrições) | `messages.text_raw` | cifrado (Fernet) | retenção do texto bruto |
| Texto mascarado | `messages.text_masked` | sem dado pessoal estruturado | com a conversa |
| Áudios | `RADAR_DATA_DIR/media/` | só lidos com permissão de revelar | retenção de mídia |
| Nome/telefone do cliente e dos participantes | `conversations` | cifrado; o painel mostra pseudônimo ("Cliente 7F3A") | com a conversa ou a pedido do titular |
| Nome do arquivo enviado | `imports.filename` | cifrado | com a conversa |
| Índice de titulares | `pii_index` | só HMAC-SHA256 por empresa, nunca o dado | com a conversa ou a pedido do titular |
| Fotos, vídeos e documentos do export | — | **não são guardados** | — |
| WhatsApp conectado: sessão do número | banco `evolution` (Evolution API) | só no servidor; a Evolution não guarda as mensagens | ao desconectar |
| WhatsApp conectado: contatos que deixaram de ser capturados | `whatsapp_ignored_contacts` | só HMAC, nunca o telefone | com a conexão |
| Arquivo enviado (zip/txt) | `RADAR_DATA_DIR/uploads/` | — | assim que é processado |
| Trilha de auditoria | `audit_logs` | sem dado pessoal de clientes | não é apagada pela API |

Princípios aplicados (art. 6º):

- **Minimização:** do export, só o texto e os áudios entram; anexos não são extraídos.
- **Necessidade:** o painel e a API mostram o texto mascarado por padrão. O original só aparece
  com "revelar", para papéis autorizados, e cada acesso é auditado.
- **Segurança:** o banco vazado sozinho não expõe CPF, telefone nem a conversa em claro.

## 4. Mascaramento de dados pessoais

Antes de qualquer análise, cada mensagem passa pela etapa de privacidade do pipeline, que troca
os dados pessoais por marcadores do tipo:

```
Meu CPF é 529.982.247-25, cel (11) 91234-5678   →   Meu CPF é [CPF], cel [TELEFONE]
```

**Tipos detectados:** `CPF`, `CNPJ` (inclusive o alfanumérico), `RG`, `TELEFONE`, `EMAIL`,
`ENDERECO`, `CEP`, `PIX`, `CONTA_BANCARIA` (agência, conta e número de cartão), `PLACA` e
`NOME_PESSOA`.

**Camadas** (todas registradas na análise):

1. **Regex + validadores + contexto.** Dígitos verificadores de CPF e CNPJ, DDDs válidos,
   algoritmo de Luhn para cartões e palavras de contexto ("meu cpf é…", "chave pix…", "placa…").
   Na dúvida, mascara: um número *formatado* como CPF ou telefone é mascarado mesmo com dígito
   errado; um número *sem formatação* só é mascarado se passar no validador ou se o contexto
   disser o que ele é.
2. **Nomes dos participantes.** O export traz o nome de quem escreveu; ele é procurado no texto
   (sem diferenciar acento ou maiúscula), junto com o primeiro nome.
3. **Modelo próprio de NER** (`pii-ner-ptbr`), treinado só com dados sintéticos, para nomes e
   endereços escritos de qualquer jeito. Entra na fase de modelos próprios; até lá, as camadas 1
   e 2 operam sozinhas.

**Trava de saída.** Todo texto que vai sair da máquina (LLM em nuvem, webhook) passa de novo pela
detecção. Se ainda houver CPF, telefone, e-mail ou outro identificador estruturado, o envio é
recusado (`UnmaskedDataError`) e a mensagem de erro não repete o dado.

**Limitações conhecidas.** Nenhum detector é perfeito. A regex não reconhece nomes escritos em
minúsculas fora de contexto ("falei com a fernanda") nem endereços sem número e sem palavra de
contexto. A empresa pode desligar a máscara de nomes (`mask_person_names`); dados estruturados
continuam sempre mascarados.

## 5. LLMs: nuvem, local ou desligado

| `RADAR_LLM_MODE` | O que sai da máquina |
|---|---|
| `cloud` | Só texto **mascarado**, para Groq → Gemini → OpenRouter (na ordem configurada) |
| `local` | Nada. A análise usa o Ollama na própria infraestrutura |
| `off` | Nada. Só regras e classificador próprio |

No modo `cloud`, mesmo mascarado, o texto pode conter dados pessoais indiretos (contexto que
permita identificar alguém). Os provedores ficam fora do Brasil: isso é **transferência
internacional** (art. 33). Avalie os termos de cada provedor e informe os titulares. Para o maior
nível de proteção, use o modo `local`. Cada empresa pode escolher o modo nas configurações.

## 6. Retenção

Cada empresa define três prazos, em dias, contados a partir de quando o Radar **recebeu** o dado
(não da data da mensagem: importar um export antigo não apaga o original no mesmo instante).
Zero desliga a regra.

| Configuração | Padrão | O que apaga | O que fica |
|---|---|---|---|
| `retention_raw_days` | 90 | texto original das mensagens e nomes dos anexos | texto mascarado, análises, alertas |
| `retention_media_days` | 30 | arquivos de áudio | a transcrição (segue a regra do texto) |
| `retention_conversation_days` | 0 (nunca) | a conversa inteira, se nada novo chegou no período | — |

- Mensagem que ainda não tinha sido mascarada é mascarada **antes** de perder o original.
- O agendador (`radar scheduler`) aplica a política a cada 6 horas.
- Manualmente: `radar retention-run` (todas as empresas; `--dry-run` só simula) ou
  `POST /api/v1/privacy/retention/run`. `GET /api/v1/privacy/retention` mostra a política e o
  que seria apagado agora.
- Toda execução que apaga algo fica na auditoria (`privacy.retention_run`).

Os padrões das empresas novas vêm de `RADAR_DEFAULT_RETENTION_RAW_DAYS` e
`RADAR_DEFAULT_RETENTION_MEDIA_DAYS`.

## 7. Direitos do titular

O Radar localiza um titular pelo **HMAC** dos identificadores informados (nome completo,
telefone, CPF, e-mail…), sem precisar guardar nenhum deles em claro. Formatos diferentes do mesmo
dado são equivalentes (`529.982.247-25` = `52998224725`; `+55 11 91234-5678` = `(11) 91234-5678`).

Uma conversa se relaciona com o titular de duas formas:

- **participante:** ele é o cliente da conversa;
- **mencionado:** um dado dele aparece numa conversa de outra pessoa ("o CPF do meu marido é…").

| Direito (art. 18) | Como atender | Endpoint |
|---|---|---|
| Confirmação e acesso (I, II) | localizar e exportar | `POST /api/v1/privacy/subjects/search` · `/export` |
| Portabilidade (V) | o relatório exportado é JSON | `POST /api/v1/privacy/subjects/export` |
| Eliminação (VI) | excluir | `POST /api/v1/privacy/subjects/delete` |
| Informação sobre compartilhamento (VII) | seção 5 deste documento | — |

Os identificadores vão no corpo da requisição (nunca na URL, para não ficarem em logs de proxy):

```bash
curl -X POST http://localhost:3000/api/v1/privacy/subjects/search \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"identifiers": ["Roberto Lima", "529.982.247-25", "+55 11 91234-5678"]}'
```

**Exportação.** Conversas em que o titular participa vão inteiras, com o texto original (ainda
não apagado pela retenção). Conversas de terceiros entram só com as mensagens que têm o dado dele,
e mascaradas, porque o resto pode conter dados de outras pessoas.

**Exclusão.** Exige `"confirm": true` e não tem volta:

- conversas em que o titular participa são excluídas inteiras (mensagens, áudios, análises);
- nas conversas de terceiros, o texto original das mensagens que o mencionam é apagado (o texto
  mascarado fica, para a análise da outra pessoa continuar fazendo sentido);
- as entradas dele no índice de titulares são removidas.

Antes de excluir, avalie as hipóteses de **conservação** do art. 16 (cumprimento de obrigação
legal ou regulatória, exercício regular de direitos em processo): elas podem exigir manter parte
dos dados. Localizar, exportar e excluir exigem a permissão `privacy:manage` (papel `admin`) e
ficam na auditoria sem o identificador procurado.

## 8. Controle de acesso e auditoria

| Papel | Vê texto mascarado | Revela original e ouve áudio | Gerencia privacidade |
|---|---|---|---|
| `admin` | sim | sim* | sim |
| `gestor` | sim | sim* | não |
| `auditor` | sim | sim* | não |
| `vendedor` | só das próprias conversas | não | não |
| token de API | sim (escopo `read`) | nunca | não |

\* Só se o papel estiver em `reveal_roles` nas configurações da empresa.

Ficam na trilha de auditoria (`audit_logs`), entre outros: leitura de conversa
(`conversation.viewed`), revelação do original ou do áudio (`conversation.pii_revealed`),
exclusão, buscas, exportações e exclusões de titular (`privacy.subject_*`) e execuções de
retenção (`privacy.retention_run`). Os registros guardam quem, quando, IP e quantidades — nunca o
dado pessoal consultado. A API não altera nem apaga registros de auditoria.

## 9. Segurança

- **Cifragem em repouso:** texto original, nomes e nomes de arquivo usam Fernet
  (AES-128-CBC + HMAC-SHA256), com chave derivada de `RADAR_SECRET_KEY` por HKDF.
  **Trocar a `RADAR_SECRET_KEY` torna ilegíveis os dados já cifrados.** Guarde-a num cofre de
  segredos e inclua-a no plano de recuperação de desastre.
- **Índice de titulares:** HMAC-SHA256 com chave própria derivada do mesmo segredo e com o id da
  empresa na mensagem: o mesmo CPF gera hashes diferentes em empresas diferentes.
- **Isolamento entre empresas:** toda consulta é filtrada pela empresa do usuário; recurso de
  outra empresa responde 404.
- **Uploads:** proteção contra zip bomb, path traversal e arquivos gigantes; o arquivo é apagado
  logo depois de processado.
- **Transporte:** publique o Radar atrás de HTTPS e ligue `RADAR_COOKIE_SECURE=true`.
- **Backups:** os backups do PostgreSQL e de `RADAR_DATA_DIR` contêm os mesmos dados; cifre-os e
  aplique a eles a mesma política de retenção.
- **Incidentes:** em caso de incidente de segurança com risco aos titulares, o controlador deve
  comunicar a ANPD e os titulares (art. 48). A trilha de auditoria ajuda a dimensionar o ocorrido.

## 10. WhatsApp conectado (ao vivo)

Conectar o número inteiro do vendedor traz **tudo** o que chega nele. Por isso:

- **Recomende WhatsApp Business com número só de trabalho.** O painel mostra essa recomendação
  antes de conectar. Grupos, status e canais nunca entram, e o histórico anterior à conexão não é
  importado.
- **Conversa pessoal sai com aprovação:** o vendedor pede a remoção e a gestão aprova; a conversa
  é apagada (mensagens, áudios e análise) e aquele contato deixa de ser capturado. O pedido e a
  decisão ficam na auditoria.
- **Informe a equipe** de que o número conectado é monitorado, e os clientes, no aviso de
  privacidade, como para o export.
- O Radar só lê: não envia mensagens nem marca nada como lido.

## 11. Checklist para quem vai usar

- [ ] Definir e documentar a base legal (e o teste de balanceamento, se for legítimo interesse).
- [ ] Atualizar o aviso de privacidade para clientes e informar a equipe de vendas.
- [ ] Escolher o modo de LLM (`local` para o máximo de proteção) e registrar a transferência
      internacional, se usar `cloud`.
- [ ] Ajustar os prazos de retenção à política da empresa e deixar o `radar scheduler` rodando.
- [ ] Restringir `reveal_roles` a quem realmente precisa ver o original.
- [ ] Definir uma `RADAR_SECRET_KEY` forte, guardá-la num cofre e cifrar os backups.
- [ ] Publicar com HTTPS e `RADAR_COOKIE_SECURE=true`.
- [ ] Definir quem atende pedidos de titulares e o prazo de resposta.
- [ ] Revisar periodicamente a trilha de auditoria.
- [ ] Com o WhatsApp conectado: usar números só de trabalho (de preferência WhatsApp Business) e
      informar a equipe de que eles são monitorados.
