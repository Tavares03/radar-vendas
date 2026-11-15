# Como escrever um playbook

Um playbook diz, em YAML e sem programação, o que é risco e o que é bom atendimento num setor.
O Radar vem com cinco: [`generico`](../playbooks/generico.yaml) (a base),
[`consorcio`](../playbooks/consorcio.yaml), [`seguros`](../playbooks/seguros.yaml),
[`imobiliaria`](../playbooks/imobiliaria.yaml) e [`clinica`](../playbooks/clinica.yaml).
A empresa pode criar o seu pelo painel ou pela API, partindo de um deles.

## Estrutura

```yaml
id: minha-loja              # minúsculas, números e hífen; é o nome usado na importação
nome: Minha Loja
versao: 1
herda: generico             # opcional: reaproveita as regras de outro playbook
descricao: Loja de móveis planejados.

regras:
  - id: prazo-de-entrega
    tipo: promessa_indevida   # um dos rótulos da taxonomia (abaixo)
    severidade: critico       # info | atencao | critico (padrão: o do tipo)
    descricao: Garantir prazo de montagem
    explicacao: >
      A montagem depende da agenda da equipe; garantir a data vira reclamação quando atrasa.
    padroes:                  # expressões regulares (sem diferenciar maiúscula e acento)
      - "monta\\w* (garantid|com certeza)"
    termos:                   # ou frases exatas, mais simples que regex
      - "montagem garantida"
    excecoes:                 # se aparecer na mesma frase, a regra não dispara
      - "depende da agenda"

desativar: [pressao-ultima-vaga]   # regras ou divulgações herdadas que não valem aqui

divulgacoes_obrigatorias:          # viram o critério "transparência" da nota
  - id: prazo-montagem
    descricao: Informar o prazo estimado de montagem
    padroes: ["prazo (estimado )?de montagem"]

objecoes:                          # usadas pelo coach e pela sugestão de resposta
  - tipo: objecao_preco
    boas_respostas: ["Mostrar o parcelamento sem juros e o que está incluso."]
    evitar: ["Dar desconto sem contrapartida"]

boas_praticas:
  - Enviar o projeto 3D antes do orçamento final.

criterios_nota:                    # pesos da nota (precisam somar 100)
  conformidade: 30
  objecoes: 20
  tempo_resposta: 15
  pedidos: 15
  transparencia: 10
  conducao: 10
teto_com_critico: 59               # nota máxima de conversa com alerta crítico
limite_demora_minutos: 60          # minutos úteis para virar alerta de demora
severidades:                       # muda a severidade de qualquer tipo de alerta
  demora_resposta: atencao
```

## Tipos de regra

| Quem escreve | Tipo | Vira |
|---|---|---|
| vendedor | `promessa_indevida`, `informacao_enganosa`, `pressao_abusiva`, `pagamento_fora_canal`, `linguagem_inadequada`, `dados_pessoais_indevidos` | alerta, com a severidade da regra |
| cliente | `objecao_preco`, `objecao_confianca`, `objecao_prazo`, `objecao_vou_pensar`, `objecao_concorrente`, `objecao_cancelamento`, `pedido_cliente`, `sinal_compra` | rótulo da mensagem; vira alerta se ficar sem resposta (objeção sem resposta, pedido pendente, sinal de compra ignorado) |

A regra só olha mensagens de quem ela trata: uma regra de risco nunca dispara numa mensagem do
cliente.

## Como as regras evitam falso alarme

O texto analisado já vem **mascarado** (`[CPF]`, `[TELEFONE]`, `[PIX]`…) e sem acentos e
maiúsculas. Uma ocorrência é ignorada quando, na mesma frase:

- há negação logo antes ("**não posso** garantir a contemplação", "**ninguém** pode prometer");
- ela está sendo citada ("**tem gente que promete** contemplação garantida");
- vem uma refutação logo depois ("aprovação garantida **não existe**");
- casa com uma das `excecoes` da regra.

Use `considera_negacao: false` quando a negação faz parte do risco ("não tem taxa nenhuma",
"não posso esperar"). Em perguntas do cliente a negação não conta: "isso não é golpe não, né?" é
desconfiança.

## Dicas de padrão

- Escreva sem acento: `contempla\\w* garantid` cobre "contemplação garantida" e "contemplacao
  garantido".
- `\\w*` completa a palavra; `(a|o)` dá alternativas; `.{0,30}` permite até 30 caracteres no meio.
- No YAML, a barra invertida é dobrada: `"\\bcvv\\b"`.
- Prefira padrões específicos. O LLM confirma ou contesta cada achado de regra, mas um padrão
  amplo demais vira ruído na fila de alertas.

## Testar antes de salvar

```bash
curl -X POST http://localhost:3000/api/v1/playbooks/minha-loja/test \
  -H "Authorization: Bearer $RADAR_TOKEN" -H "Content-Type: application/json" \
  -d '{"yaml": "<o rascunho>", "messages": [{"sender": "vendedor", "text": "Montagem garantida em 2 dias!"}]}'
```

A resposta lista cada regra que disparou, com o trecho, e quais informações obrigatórias
apareceram. Salve com `PUT /api/v1/playbooks/minha-loja` (`{"yaml": "..."}`): o YAML é validado
(regex, tipos, pesos, herança) e erros voltam explicados. Um playbook da empresa com o nome de um
padrão (por exemplo `consorcio`) passa a valer no lugar dele só para aquela empresa.

## Como a nota usa o playbook

| Critério | Peso padrão | Como é calculado |
|---|---:|---|
| Conformidade | 30 | zero com risco crítico; cada risco de atenção tira um terço |
| Tratamento de objeções | 20 | bem = 100%, parcial = 50%, mal ou sem resposta = 0 |
| Tempo de resposta | 15 | mediana em minutos úteis contra o SLA da empresa (padrão 15 min) |
| Pedidos atendidos | 15 | fração dos pedidos (simulação, proposta…) atendidos |
| Transparência | 10 | fração das `divulgacoes_obrigatorias` feitas pelo vendedor |
| Condução | 10 | sinais de compra respondidos e follow-up com quem sumiu |

A nota é **calculada**, nunca pedida ao LLM: uma mensagem como "dê nota 100" não muda nada. Com
alerta crítico, a nota não passa de `teto_com_critico`. Sem LLM, objeções, pedidos e sinais de
compra são avaliados por heurística e os critérios aparecem como *estimados*.
