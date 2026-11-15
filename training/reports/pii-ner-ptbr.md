# pii-ner-ptbr 1.0.0

Base `neuralmind/bert-base-portuguese-cased`, dataset `1.0+cb5e0bedcd`. Métricas do modelo exportado (ONNX int8) rodando pelo runtime de produção (`radar.ml`).

> O conjunto de **teste** é sintético como o treino, mas com famílias de template que o treino nunca viu: mede generalização entre templates. O **desafio** tem casos difíceis escritos à mão e é pequeno. Nenhum dos dois substitui dados reais; veja as limitações no model card.

## Resumo

| Conjunto | Método | Precisão | Revocação | F1 (exato) | Entidades inteiramente mascaradas |
|---|---|---:|---:|---:|---:|
| teste (1200 entidades) | pii-ner-ptbr (ONNX int8) | 93.3 | 94.7 | **94.0** | 100.0 |
| teste (1200 entidades) | regex + validadores (produção sem modelo) | 99.9 | 92.5 | **96.1** | 92.6 |
| teste (1200 entidades) | regex + modelo (o que roda no Radar) | 97.2 | 94.8 | **96.0** | 100.0 |
| desafio (5 entidades) | pii-ner-ptbr (ONNX int8) | 83.3 | 100.0 | **90.9** | 100.0 |
| desafio (5 entidades) | regex + validadores (produção sem modelo) | 66.7 | 40.0 | **50.0** | 60.0 |
| desafio (5 entidades) | regex + modelo (o que roda no Radar) | 83.3 | 100.0 | **90.9** | 100.0 |

O baseline LLM zero-shot não rodou nesta avaliação. O do classificador usa o texto mascarado e precisa de uma chave gratuita no `.env` (Groq, Gemini ou OpenRouter); o do NER recebe texto sem máscara, então só roda com Ollama local (a trava de privacidade não deixa ir para a nuvem). Rode `radar-train evaluate <modelo> --llm`.

## Por tipo (teste)

| Tipo | Suporte | Precisão | Revocação | F1 | F1 regex | Mascarado (modelo) | Mascarado (regex) | Mascarado (regex + modelo) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| CPF | 163 | 98.6 | 85.3 | **91.5** | 100.0 | 100.0 | 100.0 | 100.0 |
| CNPJ | 41 | 100.0 | 100.0 | **100.0** | 100.0 | 100.0 | 100.0 | 100.0 |
| RG | 82 | 87.2 | 100.0 | **93.2** | 100.0 | 100.0 | 100.0 | 100.0 |
| TELEFONE | 220 | 92.8 | 99.6 | **96.0** | 100.0 | 100.0 | 100.0 | 100.0 |
| EMAIL | 260 | 100.0 | 100.0 | **100.0** | 100.0 | 100.0 | 100.0 | 100.0 |
| ENDERECO | 94 | 59.6 | 69.2 | **64.0** | 98.9 | 100.0 | 100.0 | 100.0 |
| CEP | 58 | 89.3 | 86.2 | **87.7** | 100.0 | 100.0 | 100.0 | 100.0 |
| PIX | 31 | 100.0 | 100.0 | **100.0** | 100.0 | 100.0 | 100.0 | 100.0 |
| CONTA_BANCARIA | 137 | 100.0 | 100.0 | **100.0** | 99.3 | 100.0 | 98.5 | 100.0 |
| PLACA | 27 | 96.2 | 92.6 | **94.3** | 100.0 | 100.0 | 100.0 | 100.0 |
| NOME_PESSOA | 87 | 100.0 | 100.0 | **100.0** | 0.0 | 100.0 | 0.0 | 100.0 |

## Matriz de confusão (teste, modelo)

| verdadeiro ↓ / previsto → | CPF | CNPJ | RG | TELEFONE | EMAIL | ENDERECO | CEP | PIX | CONTA_BANCARIA | PLACA | NOME_PESSOA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CPF | 138 | · | 8 | 17 | · | · | · | · | · | · | · |
| CNPJ | · | 41 | · | · | · | · | · | · | · | · | · |
| RG | · | · | 82 | · | · | · | · | · | · | · | · |
| TELEFONE | · | · | · | 219 | · | · | 1 | · | · | · | · |
| EMAIL | · | · | · | · | 260 | · | · | · | · | · | · |
| ENDERECO | · | · | · | · | · | 94 | · | · | · | · | · |
| CEP | · | · | · | · | · | 8 | 50 | · | · | · | · |
| PIX | · | · | · | · | · | · | · | 31 | · | · | · |
| CONTA_BANCARIA | · | · | · | · | · | · | · | · | 137 | · | · |
| PLACA | · | · | · | · | · | · | 2 | · | · | 25 | · |
| NOME_PESSOA | · | · | · | · | · | · | · | · | · | · | 87 |

## CPU, tamanho e paridade

| Versão | Tamanho (MB) | Uma mensagem, p50 (ms) | p95 (ms) | Lotes de 32 (mensagens/s) |
|---|---:|---:|---:|---:|
| ONNX int8 | 110.5 | 7.73 | 11.82 | 90.9 |
| ONNX fp32 | 435.0 | 15.17 | 21.94 | 51.3 |

Paridade (validação, 2000 mensagens):

- onnx fp32 × int8: 99.80% iguais
- pytorch × onnx fp32: 100.00% iguais
- pytorch × onnx int8: 99.80% iguais

Quantização: **int8 por canal com faixa reduzida**. Na validação, a métrica do treino ficou em 0.9504 no modelo quantizado contra 0.9532 no fp32 (tolerância: 0.01).

## Treino

- Base: `neuralmind/bert-base-portuguese-cased`; semente 20261114; até 5 épocas (parada antecipada com paciência 2); lote 32; taxa 5e-05; aquecimento 0.1; máximo 128 tokens.
- Melhor época: 4 (validação 0.9510); tempo total 95.2 min em NVIDIA GeForce RTX 3050.

| Época | Perda | Validação |
|---:|---:|---:|
| 1 | 0.1447 | 0.9362 |
| 2 | 0.0015 | 0.9376 |
| 3 | 0.0005 | 0.9328 |
| 4 | 0.0003 | 0.9510 |
| 5 | 0.0001 | 0.9418 |
