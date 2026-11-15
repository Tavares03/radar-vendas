# Comparação de encoders

Dataset `1.0+cb5e0bedcd`, 1 época(s) por tarefa, mesma semente. Validação:
NER = F1 micro exato (tipo e fronteiras); classificador = F1 macro com limiar calibrado.
Latência: PyTorch fp32 em CPU, uma mensagem por vez (o modelo final roda em ONNX int8,
bem mais rápido; aqui vale a comparação entre eles).

| Encoder | Parâmetros (mi) | NER F1 | Classificador F1 macro | CPU p50 (ms) | Épocas NER + classificador (s) |
|---|---:|---:|---:|---:|---:|
| `neuralmind/bert-base-portuguese-cased` | 108.4 | 0.9706 | 0.5697 | 44.33 | 511 |
| `pablocosta/bertabaporu-base-uncased` | 134.6 | 0.8567 | 0.5082 | 42.27 | 536 |
| `jhu-clsp/mmBERT-small` | 140.7 | 0.8937 | 0.3936 | 26.25 | 685 |
