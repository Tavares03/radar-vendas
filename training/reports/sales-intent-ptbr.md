# sales-intent-ptbr 1.0.0

Base `neuralmind/bert-base-portuguese-cased`, dataset `1.0+cb5e0bedcd`. Métricas do modelo exportado (ONNX int8) rodando pelo runtime de produção (`radar.ml`).

> O conjunto de **teste** é sintético como o treino, mas com famílias de template que o treino nunca viu: mede generalização entre templates. O **desafio** tem casos difíceis escritos à mão e é pequeno. Nenhum dos dois substitui dados reais; veja as limitações no model card.

## Resumo

| Conjunto | Método | Precisão (micro) | Revocação (micro) | F1 micro | F1 macro |
|---|---|---:|---:|---:|---:|
| teste (9194 mensagens) | sales-intent-ptbr (ONNX int8) | 87.6 | 37.9 | **52.9** | 43.8 |
| teste (9194 mensagens) | regras dos playbooks | 100.0 | 90.9 | **95.2** | 94.4 |
| teste (9194 mensagens) | TF-IDF + regressão logística | 71.1 | 24.3 | **36.2** | 22.5 |
| teste (9194 mensagens) | regras + modelo (o que roda no Radar) | 94.6 | 94.4 | **94.5** | 94.2 |
| desafio (43 mensagens) | sales-intent-ptbr (ONNX int8) | 85.7 | 50.0 | **63.2** | 51.5 |
| desafio (43 mensagens) | regras dos playbooks | 100.0 | 66.7 | **80.0** | 63.6 |
| desafio (43 mensagens) | TF-IDF + regressão logística | 50.0 | 16.7 | **25.0** | 15.2 |
| desafio (43 mensagens) | regras + modelo (o que roda no Radar) | 90.0 | 75.0 | **81.8** | 72.7 |

O baseline LLM zero-shot não rodou nesta avaliação. O do classificador usa o texto mascarado e precisa de uma chave gratuita no `.env` (Groq, Gemini ou OpenRouter); o do NER recebe texto sem máscara, então só roda com Ollama local (a trava de privacidade não deixa ir para a nuvem). Rode `radar-train evaluate <modelo> --llm`.

## Por rótulo (teste)

| Rótulo | Suporte | Limiar | Precisão | Revocação | F1 | F1 regras | F1 TF-IDF |
|---|---:|---:|---:|---:|---:|---:|---:|
| Promessa indevida (`promessa_indevida`) | 64 | 0.95 | 87.3 | 75.0 | **80.7** | 87.7 | 45.5 |
| Informação enganosa ou omissão (`informacao_enganosa`) | 98 | desligado | 0.0 | 0.0 | **0.0** | 93.5 | 36.7 |
| Pressão abusiva ou urgência falsa (`pressao_abusiva`) | 62 | 0.25 | 86.2 | 40.3 | **54.9** | 100.0 | 0.0 |
| Pagamento fora do canal oficial (`pagamento_fora_canal`) | 31 | desligado | 0.0 | 0.0 | **0.0** | 100.0 | 0.0 |
| Linguagem ofensiva ou inadequada (`linguagem_inadequada`) | 33 | desligado | 0.0 | 0.0 | **0.0** | 96.9 | 0.0 |
| Coleta ou compartilhamento indevido de dados (`dados_pessoais_indevidos`) | 42 | 0.50 | 100.0 | 100.0 | **100.0** | 98.8 | 72.7 |
| Objeção de preço (`objecao_preco`) | 240 | 0.95 | 96.3 | 32.9 | **49.1** | 94.3 | 41.5 |
| Objeção de confiança (`objecao_confianca`) | 83 | desligado | 0.0 | 0.0 | **0.0** | 77.0 | 0.0 |
| Objeção de prazo (`objecao_prazo`) | 121 | 0.95 | 73.0 | 44.6 | **55.4** | 96.1 | 0.0 |
| Objeção "vou pensar" (`objecao_vou_pensar`) | 108 | 0.85 | 88.6 | 86.1 | **87.3** | 98.1 | 1.8 |
| Objeção de concorrente (`objecao_concorrente`) | 77 | 0.95 | 100.0 | 59.7 | **74.8** | 87.6 | 0.0 |
| Objeção de cancelamento (`objecao_cancelamento`) | 125 | desligado | 0.0 | 0.0 | **0.0** | 99.6 | 63.0 |
| Sinal de compra (`sinal_compra`) | 221 | 0.10 | 100.0 | 38.5 | **55.6** | 93.8 | 0.0 |
| Pedido do cliente (`pedido_cliente`) | 500 | 0.95 | 80.6 | 42.4 | **55.6** | 97.9 | 54.1 |

**Rótulos desligados:** informação enganosa ou omissão, pagamento fora do canal oficial, linguagem ofensiva ou inadequada, objeção de confiança, objeção de cancelamento. Em nenhum limiar o modelo alcançou precisão 0,70 neles na validação, então em produção ele não os aponta: esses casos ficam com as regras do playbook e com o LLM. Um alerta apontado só pelo modelo precisa ser confiável.

## Matriz de confusão (teste, modelo)

Linha = rótulo verdadeiro; coluna = o que o modelo disse.

| verdadeiro ↓ / previsto → | promessa_indevida | informacao_enganosa | pressao_abusiva | pagamento_fora_canal | linguagem_inadequada | dados_pessoais_indevidos | objecao_preco | objecao_confianca | objecao_prazo | objecao_vou_pensar | objecao_concorrente | objecao_cancelamento | sinal_compra | pedido_cliente | nenhum |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| promessa_indevida | 48 | · | · | · | · | · | · | · | · | · | · | · | · | · | 16 |
| informacao_enganosa | 6 | · | 4 | · | · | · | · | · | · | · | · | · | · | · | 88 |
| pressao_abusiva | · | · | 25 | · | · | · | · | · | · | · | · | · | · | · | 37 |
| pagamento_fora_canal | · | · | · | · | · | · | · | · | · | · | · | · | · | · | 31 |
| linguagem_inadequada | · | · | · | · | · | · | · | · | · | · | · | · | · | · | 33 |
| dados_pessoais_indevidos | · | · | · | · | · | 42 | · | · | · | · | · | · | · | · | · |
| objecao_preco | · | · | · | · | · | · | 79 | · | · | · | · | · | · | · | 161 |
| objecao_confianca | · | · | · | · | · | · | · | · | · | · | · | · | · | · | 83 |
| objecao_prazo | · | · | · | · | · | · | · | · | 54 | · | · | · | · | · | 67 |
| objecao_vou_pensar | · | · | · | · | · | · | · | · | · | 93 | · | · | · | · | 15 |
| objecao_concorrente | · | · | · | · | · | · | 3 | · | · | · | 46 | · | · | · | 28 |
| objecao_cancelamento | · | · | · | · | · | · | · | · | 1 | · | · | · | · | · | 124 |
| sinal_compra | · | · | · | · | · | · | · | · | · | · | · | · | 85 | 39 | 97 |
| pedido_cliente | · | · | · | · | · | · | · | · | · | · | · | · | · | 212 | 288 |
| nenhum | 1 | · | · | · | · | · | · | · | 19 | 12 | · | · | · | 12 | · |

## CPU, tamanho e paridade

| Versão | Tamanho (MB) | Uma mensagem, p50 (ms) | p95 (ms) | Lotes de 32 (mensagens/s) |
|---|---:|---:|---:|---:|
| ONNX int8 | 110.7 | 7.93 | 13.27 | 78.4 |
| ONNX fp32 | 437.3 | 14.81 | 22.06 | 50.9 |

Paridade (validação, 2000 mensagens):

- onnx fp32 × int8 decisoes: 96.75% iguais
- onnx fp32 × int8 dif max prob: 0.8951
- pytorch × onnx fp32 dif max prob: 1e-05
- pytorch × onnx int8 decisoes: 96.75% iguais

Quantização: **uint8**. Na validação, a métrica do treino ficou em 0.5780 no modelo quantizado contra 0.5819 no fp32 (tolerância: 0.01).
Receitas medidas e descartadas: int8 por canal com faixa reduzida (0.5677).

## Treino

- Base: `neuralmind/bert-base-portuguese-cased`; semente 20261114; até 6 épocas (parada antecipada com paciência 2); lote 32; taxa 3e-05; aquecimento 0.1; máximo 128 tokens.
- Melhor época: 3 (validação 0.5607); tempo total 21.2 min em NVIDIA GeForce RTX 3050.

| Época | Perda | Validação |
|---:|---:|---:|
| 1 | 0.1046 | 0.5024 |
| 2 | 0.0034 | 0.5062 |
| 3 | 0.0012 | 0.5607 |
| 4 | 0.0006 | 0.5427 |
| 5 | 0.0003 | 0.4441 |
