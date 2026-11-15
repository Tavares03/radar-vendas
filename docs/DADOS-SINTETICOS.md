# Dados sintéticos

O pacote [`synthetic/`](../synthetic) (`radar_synth`) gera conversas de venda realistas em PT-BR
no formato de export do WhatsApp, **com a resposta certa junto**: o rótulo de cada mensagem, a
posição exata de cada dado pessoal e os alertas que o Radar deveria levantar. É a base para
treinar os modelos próprios, rodar os evals e a demo — sem uma única conversa real.

## Uso rápido

```bash
uv run radar-synth generate                 # 3000 treino / 500 validação / 500 teste + desafio
uv run radar-synth sample --sector seguros --seller problematico --out conversa.zip
uv run radar-synth review --dataset data/generated/<versão> --n 40   # amostra para revisão humana
uv run radar-synth export-hf --dataset data/generated/<versão>       # pasta pronta para o HF Hub
uv run radar-synth samples                  # regenera data/samples/synthetic (versionado)
uv run radar-synth demo                     # regenera data/samples/demo (a equipe da demonstração)
```

O `.zip` de `sample` entra no Radar como um export de verdade (`POST /api/v1/imports` ou pelo
painel), com áudios cujas transcrições vêm junto no zip.

## Como uma conversa nasce

```
perfil do vendedor (bom · médio · problemático)  ┐
perfil do cliente (decidido · pesquisador · ...) ├─► roteiro pelo funil ─► atos de fala
setor (consórcio · seguros · imobiliária · ...)  ┘                              │
                                                                                 ▼
                    banco de templates do setor ─► template ─► slots preenchidos + ruído
                                                                                 │
                                                                                 ▼
             mensagens + rótulos + dados pessoais com posição + alertas esperados
```

1. **Roteiro.** Contato → qualificação → apresentação → proposta → negociação → fechamento, com
   desvios sorteados pelos perfis: o vendedor problemático promete contemplação quando o cliente
   pergunta se é garantido, pede pagamento no PIX pessoal, ignora objeções; o bom explica as
   condições obrigatórias e nega promessas ("não posso garantir…").
2. **Atos de fala** (`cliente.objecao_preco`, `vendedor.promessa_indevida`…) carregam os rótulos
   do classificador. Os rótulos de cada mensagem vêm do ato que a gerou, nunca de heurística.
3. **Templates** ficam em [`banks/`](../synthetic/src/radar_synth/banks): `comum.yaml` vale para
   todos os setores e cada setor acrescenta vocabulário, promessas proibidas, divulgações
   obrigatórias e perguntas típicas. Perguntas e respostas formam pares pela chave da família.
4. **Slots** (`{cpf}`, `{nome_cliente}`, `{produto}`…) recebem dados falsos ou o vocabulário do
   setor. Os dados pessoais entram por slot, então a posição de cada um é exata.
5. **Ruído** de WhatsApp só nos trechos literais: abreviações (`vc`, `pq`, `tb`), acentos
   esquecidos, erros de digitação, emojis, risadas, mensagens picotadas (`a || b`) e "áudios"
   (texto com marcas de fala).
6. **Tempo**: respostas com atraso realista por perfil, só no horário de atendimento; follow-up em
   outro dia. `demora_resposta` conta minutos de horário comercial (seg–sex, 8h–18h).

## O que vem anotado

| Nível | Campos |
|---|---|
| Mensagem | `labels` (riscos do vendedor; objeções e intenção do cliente), `pii` (`type`, `start`, `end`, `value`), `kind` (`texto`/`audio`), `stage` (etapa do funil), `act` e `family` |
| Conversa | `expected_alerts` (tipo, severidade padrão, mensagem de evidência), `objections` (tipo e se foi tratada `bem`/`parcial`/`mal`/`sem_resposta`), `requests` (pedido e quem atendeu), perfis, setor, desfecho |

Os alertas esperados seguem [`DEFAULT_SEVERITY`](../backend/src/radar/taxonomy.py), a mesma
tabela que os playbooks usam quando o setor não define outra severidade.

## Splits sem vazamento de template

Uma *família* é uma ideia escrita de vários jeitos. Famílias inteiras vão para o treino ou para a
parte reservada (validação e teste), separadas por grupo (arquivo de origem + ato). Assim o teste
mede se o modelo generaliza para frases que nunca viu.

- Grupos com 3–4 famílias reservam uma, compartilhada por validação e teste; com 5 ou mais, cada
  um recebe as suas. Grupos com menos de 3 famílias ficam só no treino.
- Cada tipo de dado pessoal tem o próprio ato com 3+ famílias, então **todos os 11 tipos aparecem
  nos três splits** (há um teste garantindo isso).
- A mesma semente gera o mesmo dataset; a versão (`1.0+<hash>`) muda quando o gerador ou qualquer
  banco muda.

## Conjuntos extras

| Conjunto | Onde | Para quê |
|---|---|---|
| Desafio | [`challenge.yaml`](../synthetic/src/radar_synth/challenge.yaml) | 20 casos difíceis escritos à mão: negações, citações de promessa, sarcasmo, injeção de instrução, nome em minúsculas, números que não são dados pessoais, CPF falado em áudio |
| Fora de distribuição | `radar-synth ood` | conversas escritas inteiras por um LLM a partir de cenários; os dados pessoais que o LLM escreve são trocados por falsos nossos |
| Paráfrases | `radar-synth expand` | um LLM reescreve cada família; variantes validadas (mesmos slots, sem dado literal, negação preservada) entram na mesma família, em `banks/expanded/` |

`ood` e `expand` precisam de uma chave gratuita no `.env` (`GROQ_API_KEY`, `GEMINI_API_KEY` ou
`OPENROUTER_API_KEY`) ou do Ollama local. Use provedores diferentes para os dois, para não
treinar e avaliar com o mesmo "sotaque" de LLM.

## Revisão humana

`radar-synth review` separa uma amostra estratificada (todos os setores, perfis, rótulos e tipos
de alerta) e gera `revisao.md` (conversa legível com rótulos e dados pessoais destacados) e
`revisao.csv` (uma linha por mensagem, colunas `ok`, `correcao` e `comentario`). Correções viram
ajustes nos bancos de templates.

## Garantias testadas

- os rótulos combinam com quem fala; todo risco rotulado vira alerta esperado e vice-versa;
- o texto de cada dado pessoal bate com a posição anotada, mesmo com ruído pesado;
- CPFs, CNPJs (inclusive alfanuméricos), telefones e cartões passam nos validadores do Radar e são
  reconhecidos pelo detector com o tipo certo;
- o export gerado volta idêntico pelo parser do Radar (Android/iOS, PT/EN), e o Radar identifica
  vendedor e cliente;
- nenhum template ou vocabulário contém dado pessoal literal.

## Limitações

Veja o dataset card gerado por `export-hf`: vocabulário limitado aos templates, rótulos por
construção (herdam erros de quem escreveu os templates), "áudios" que são texto, nomes e
português do Sudeste sobre-representados.
