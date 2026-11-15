# Modelos próprios: treino, avaliação e publicação

O Radar tem dois modelos próprios, treinados **só com dados sintéticos** e servidos em ONNX int8
(CPU, sem PyTorch em produção):

| Modelo | O que faz | Onde entra no Radar |
|---|---|---|
| `pii-ner-ptbr` | NER de dados pessoais em PT-BR: CPF, CNPJ, RG, telefone, e-mail, endereço, CEP, PIX, conta bancária, placa e nome de pessoa | camada `ner` do detector de dados pessoais, somada à regex e aos nomes dos participantes |
| `sales-intent-ptbr` | classificador multirrótulo de mensagens: riscos do vendedor, objeções, sinal de compra e pedidos do cliente | camada `classificador` da análise, entre as regras e o LLM |

Métricas, matriz de confusão, comparação com os baselines, paridade e latência:
[`training/reports/pii-ner-ptbr.md`](../training/reports/pii-ner-ptbr.md),
[`training/reports/sales-intent-ptbr.md`](../training/reports/sales-intent-ptbr.md) e a escolha da
base em [`training/reports/encoders.md`](../training/reports/encoders.md).

## Usar no Radar

O Radar procura os modelos em `models/` (no Docker, `/models`, montado de `./models`):

```
models/pii-ner-ptbr/       radar_model.json, tokenizer.json, onnx/model_quantized.onnx…
models/sales-intent-ptbr/
```

| Variável | Valores |
|---|---|
| `RADAR_NER_MODEL`, `RADAR_CLASSIFIER_MODEL` | `auto` (padrão: a pasta acima; senão o id do Hub abaixo; senão a camada fica de fora), `off`, um caminho ou um id do Hugging Face |
| `RADAR_NER_HUB_ID`, `RADAR_CLASSIFIER_HUB_ID` | id no Hub (ex.: `usuario/pii-ner-ptbr`); baixa só os arquivos do runtime para o cache |
| `RADAR_ML_THREADS` | threads do ONNX Runtime por modelo (0 = padrão) |

`uv run radar models` (ou `docker compose exec api radar models`) mostra o que está em uso. Sem
modelo, nada quebra: a máscara por regex e as regras continuam, e a análise registra quais camadas
rodaram. Se um modelo não carregar, o erro vai para o log e a camada fica de fora.

## Treinar

Requisitos: GPU NVIDIA ajuda muito (uma RTX 3050 de 6 GB treina cada modelo em poucos minutos);
em CPU funciona, bem mais devagar.

```bash
uv sync --all-packages --group dev --group train   # PyTorch (CUDA no Windows e Linux), Transformers…
uv run radar-synth generate                        # dataset em data/generated/<versão>
uv run radar-train encoders                        # (opcional) compara as bases candidatas
uv run radar-train run pii-ner-ptbr                # treina, exporta, avalia, escreve relatório e card
uv run radar-train run sales-intent-ptbr
uv run radar models                                # confere que o Radar achou os dois
```

O PyTorch vem do índice `cu132` (driver com suporte a CUDA 13.2 ou mais novo). Para outra versão
de CUDA, troque o índice `pytorch-cu132` no `pyproject.toml` da raiz.

`radar-train run <modelo>`:

1. lê `training/configs/<modelo>.yaml` (base, semente, épocas, taxa de aprendizado…);
2. treina com parada antecipada pela validação (NER: F1 exato; classificador: F1 macro);
3. exporta para ONNX (fp32) e quantiza em 8 bits, **conferindo a qualidade**: cada receita de
   quantização é medida na validação contra o fp32 e só é aceita se perder no máximo 0,01 na
   métrica do treino (veja [Quantização](#quantização));
4. calibra os limiares do classificador **no modelo quantizado** e na validação, com um piso de
   precisão (`min_precision`, padrão 0,7): o rótulo que não é confiável o bastante fica desligado;
5. avalia o quantizado pelo runtime de produção (`radar.ml`) no teste e no desafio, com os baselines;
6. grava `training/reports/<modelo>.{md,json}` e o model card em `models/<modelo>/README.md`.

`radar-train evaluate <modelo>` refaz só a avaliação (por exemplo, com `--llm` depois de configurar
uma chave). `--skip-train` em `run` reaproveita os pesos e refaz exportação e avaliação.

### Quantização

Quantizar um BERT não é de graça nem previsível. A receita padrão do ONNX Runtime (int8, uma
escala por tensor) derrubou o F1 do `pii-ner-ptbr` de 0,94 para 0,63 no teste, sem erro nem aviso:
o modelo carregava, respondia rápido e errava a fronteira de quase todo telefone. Por isso
`radar-train`:

- tenta primeiro **int8 por canal com faixa reduzida** (7 bits; é o que o ONNX Runtime recomenda
  para CPUs sem VNNI, onde a soma de 16 bits pode saturar) e, se não passar, **uint8**;
- mede cada uma na validação, pelo runtime de produção, com a métrica que escolhe a melhor época
  (F1 exato no NER, F1 macro no classificador);
- aceita a primeira que fica a até 0,01 do fp32 e registra a escolha e as medidas no relatório e
  em `models/<modelo>/training.json`;
- se nenhuma passar, aponta o manifesto para `onnx/model.onnx` (fp32): o Radar fica mais lento,
  mas não fica pior em silêncio. O relatório avisa em negrito.

Se você quantizar por conta própria (outro hardware, outra ferramenta), meça antes de servir. A
paridade "% de mensagens com a mesma resposta" engana: a maioria das mensagens não tem dado
pessoal nenhum e concorda de graça.

### Reprodutibilidade

- Semente fixa na configuração (dados, inicialização, embaralhamento).
- Dataset versionado: a versão (`1.0+<hash do gerador>`) vai para o manifesto, o relatório e o card.
- Configuração, histórico por época, hardware e versões de PyTorch e Transformers ficam em
  `models/<modelo>/training.json`.
- Na GPU, operações não determinísticas do cuDNN podem mudar a terceira casa decimal entre execuções.

## Como avaliamos

- **Teste**: conversas sintéticas de famílias de template que o treino nunca viu (os splits são
  separados por família). Mede generalização entre templates, não entre "mundos": é otimista.
- **Desafio**: casos difíceis escritos à mão (negação, citação, ironia, dado pessoal disfarçado).
  Pequeno, mas é onde regras e modelos mais erram.
- NER em duas leituras: **exata** (tipo e fronteiras) e **máscara** (a entidade ficou inteira
  debaixo de alguma máscara, qualquer que seja o tipo previsto). A segunda é a que importa para a
  LGPD.
- Classificador com o filtro da análise: rótulo de vendedor só conta em mensagem do vendedor, e o
  de cliente, na do cliente.
- Limiar por rótulo escolhido na validação para o melhor F1 **entre os que acertam pelo menos 70%
  do que apontam**. Rótulo que não chega lá aparece como "desligado" no relatório e não é
  apontado em produção: sem LLM para conferir, o achado do modelo vira alerta direto, e alerta
  falso custa caro. As regras do playbook e o LLM continuam cobrindo esses casos.
- Baselines: regex e validadores (NER, o que roda sem modelo), regras dos playbooks e TF-IDF com
  regressão logística (classificador) e LLM zero-shot pelo mesmo roteador da análise.
- O LLM zero-shot do classificador recebe texto mascarado e pode usar os provedores de nuvem; o do
  NER recebe texto **sem** máscara e por isso só roda no Ollama local: a trava de privacidade não
  abre exceção nem para dado sintético.
- Paridade: PyTorch × ONNX fp32 × ONNX int8 na validação, pelo runtime de produção, mais a métrica
  do treino no fp32 e no quantizado (é ela que decide se a quantização entra).

## Publicar no Hugging Face

Precisa de um token com escrita (gratuito) em `HF_TOKEN`. Sem `--yes`, só mostra o plano:

```bash
uv run radar-synth export-hf --dataset data/generated/<versão>
uv run python scripts/publish_hf.py tudo --namespace SEU_USUARIO          # plano
uv run python scripts/publish_hf.py tudo --namespace SEU_USUARIO --yes    # publica
```

Cada modelo vai com os pesos do Transformers (para quem quiser ajustar), os dois ONNX, o manifesto
do runtime, o relatório (`metrics.json`) e o model card com o id final. Depois, em outra máquina,
basta `RADAR_NER_HUB_ID=SEU_USUARIO/pii-ner-ptbr` (e o mesmo para o classificador).

## Ciclo de melhoria

Falsos positivos marcados no painel ficam registrados na revisão dos alertas. O modelo **público**
é treinado só com dados sintéticos; retreinar com dados reais de uma empresa é uma decisão dela, com
consentimento e anonimização, e o resultado não deve ser publicado.
