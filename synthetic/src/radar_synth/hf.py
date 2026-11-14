"""Pacote do dataset para o Hugging Face Hub: arquivos por configuração e o dataset card.

A publicação em si (que exige ``HF_TOKEN``) fica em ``scripts/publish_hf.py``; aqui só se monta a
pasta, que pode ser conferida antes de subir.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from radar.taxonomy import CLASSIFIER_LABELS, PII_TYPES
from radar_synth.challenge import load_challenge
from radar_synth.dataset import SPLITS, message_rows, ner_rows

DATASET_ID = "radar-vendas-conversas-sinteticas"
_CONFIGS = ("conversations", "messages", "ner")


def _table(counts: dict[str, dict[str, int]], keys: list[str]) -> str:
    header = "| | " + " | ".join(SPLITS) + " |\n|---|" + "---:|" * len(SPLITS)
    rows = [
        f"| `{key}` | "
        + " | ".join(str(counts.get(split, {}).get(key, 0)) for split in SPLITS)
        + " |"
        for key in keys
    ]
    return "\n".join([header, *rows])


def _card(manifest: dict[str, Any]) -> str:
    data_files = []
    for config in _CONFIGS:
        files = "\n".join(
            f"  - split: {split}\n    path: {config}/{split}.jsonl" for split in SPLITS
        )
        data_files.append(f"- config_name: {config}\n  data_files:\n{files}")
    data_files.append(
        "- config_name: desafio\n  data_files:\n  - split: test\n    path: desafio/test.jsonl"
    )
    conversations = manifest["conversations"]
    labels = list(CLASSIFIER_LABELS)
    return f"""---
license: cc-by-4.0
language:
- pt
pretty_name: Radar de Vendas — conversas de venda sintéticas em PT-BR
size_categories:
- 1K<n<10K
task_categories:
- text-classification
- token-classification
tags:
- synthetic
- whatsapp
- sales
- compliance
- pii
- lgpd
- portuguese
configs:
{chr(10).join(data_files)}
---

# Radar de Vendas — conversas de venda sintéticas em PT-BR

Conversas de venda **100% sintéticas** no estilo do WhatsApp, em português do Brasil, com anotação
por mensagem de **riscos de compliance**, **objeções**, **intenção de compra** e **dados pessoais
com posição** (para NER). Feitas para treinar e avaliar os modelos do
[Radar de Vendas](https://github.com/Tavares03/radar-vendas), um supervisor de vendas open-source.

> 🇬🇧 Fully synthetic Brazilian-Portuguese WhatsApp sales conversations, annotated per message
> with compliance risks, objections, buying intent and character-level PII spans. Built to train
> a multi-label sales-message classifier and a PII NER model for Portuguese.

**Versão:** `{manifest["version"]}` · **semente:** `{manifest.get("seed")}` ·
**conversas:** {conversations.get("train", 0)} treino, {conversations.get("validation", 0)}
validação, {conversations.get("test", 0)} teste, mais um conjunto de desafio curado.

## Configurações

| Configuração | Uma linha é… | Uso |
|---|---|---|
| `conversations` | uma conversa inteira com metadados, mensagens, alertas esperados, objeções e pedidos | avaliação do sistema inteiro |
| `messages` | uma mensagem, com `labels` (multirrótulo) e quem enviou | classificador de mensagens |
| `ner` | uma mensagem, com `entities` (`type`, `start`, `end`, `value`) | NER de dados pessoais |
| `desafio` | conversas curtas escritas à mão com casos difíceis (negações, citações, injeção…) | teste de robustez |

## Como foi gerado

1. **Bancos de templates por setor** (consórcio, seguros, imobiliária, clínica e genérico),
   organizados por *ato de fala* (pedir simulação, objeção de preço, promessa indevida…). Cada
   ideia é uma *família* escrita de vários jeitos.
2. **Roteiros por perfil**: vendedor bom, médio ou problemático; cliente decidido, pesquisador,
   sensível a preço, desconfiado, indeciso ou apressado. O roteiro segue o funil e sorteia
   desvios (pedido não atendido, objeção ignorada, promessa proibida, pagamento fora do canal…).
3. **Ruído de WhatsApp**: abreviações, acentos esquecidos, erros de digitação, emojis, risadas,
   mensagens picotadas e "áudios" (texto em estilo de fala, como sairia da transcrição).
4. **Dados pessoais falsos**: CPFs e CNPJs matematicamente válidos, mas sorteados; telefones com
   DDD válido; e-mails em domínios fictícios. Inseridos por slot, então as posições são exatas.
5. **Anotação automática**: cada rótulo vem do ato que gerou a mensagem; cada dado pessoal vem
   do slot preenchido. Nada é rotulado depois, por heurística.

Opcionalmente, um LLM gratuito escreve paráfrases de cada família (validadas por regras) e um
segundo LLM escreve um conjunto fora de distribuição.

### Splits sem vazamento de template

Famílias inteiras vão para o treino ou para a parte reservada (validação e teste): o teste mede
generalização para frases que o modelo nunca viu. Grupos com 3–4 famílias reservam uma única
família, compartilhada entre validação e teste.

## Rótulos

Mensagens do vendedor: riscos (`promessa_indevida`, `informacao_enganosa`, `pressao_abusiva`,
`pagamento_fora_canal`, `linguagem_inadequada`, `dados_pessoais_indevidos`). Mensagens do cliente:
objeções (`objecao_preco`, `objecao_confianca`, `objecao_prazo`, `objecao_vou_pensar`,
`objecao_concorrente`, `objecao_cancelamento`) e intenção (`sinal_compra`, `pedido_cliente`).

Dados pessoais: {", ".join(f"`{t}`" for t in PII_TYPES)}.

### Rótulos por split

{_table(manifest["labels"], labels)}

### Dados pessoais por split

{_table(manifest["pii"], list(PII_TYPES))}

## Limitações

- **É sintético.** As conversas são plausíveis, mas mais regulares que as reais: o vocabulário é
  limitado ao que os templates (e as paráfrases) cobrem. Meça sempre também em dados reais da sua
  operação, anonimizados e com consentimento.
- **Rótulos por construção** são consistentes, mas herdam os erros de quem escreveu os templates.
  Uma amostra foi separada para revisão humana (`radar-synth review`).
- Os "áudios" são texto em estilo de fala, não saída real de um transcritor.
- Cobre cinco setores; outros setores podem usar termos que não aparecem aqui.

## Vieses

- Nomes e sobrenomes vêm de listas dos mais comuns no Brasil; nomes indígenas, estrangeiros e
  compostos incomuns estão sub-representados.
- O português é o do Sudeste urbano, com gírias gerais de WhatsApp; variantes regionais são raras.
- Os perfis "problemáticos" concentram os riscos: um modelo pode associar informalidade a risco.
  Os perfis variam o nível de ruído de forma independente para atenuar isso.

## Uso pretendido

Treinar e avaliar classificadores de mensagens de venda e modelos de NER de dados pessoais em
PT-BR; testar pipelines de mascaramento (LGPD) e de análise de conversas.

**Não use** para avaliar pessoas reais, nem como prova do que é permitido ou proibido em um
setor: a regulação muda e cada empresa tem as próprias regras.

## Privacidade

Nenhuma pessoa ou empresa real está neste dataset. Qualquer semelhança de um número sorteado com
um documento existente é coincidência: os dados foram gerados aleatoriamente para passar nos
validadores de formato.

## Licença e citação

[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.pt-br). Código do gerador: Apache-2.0.

```bibtex
@misc{{radar_vendas_sinteticas,
  title  = {{Radar de Vendas: conversas de venda sintéticas em PT-BR}},
  author = {{Gabriel Tavares}},
  year   = {{2026}},
  note   = {{Versão {manifest["version"]}}}
}}
```
"""


def build_hf_folder(dataset_dir: Path, out_dir: Path) -> Path:
    """Monta ``out_dir`` com um arquivo JSONL por configuração e split, mais o README (card)."""
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for config in _CONFIGS:
        for split in SPLITS:
            source = dataset_dir / config / f"{split}.jsonl"
            target = out_dir / config / f"{split}.jsonl"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

    challenge = out_dir / "desafio" / "test.jsonl"
    challenge.parent.mkdir(parents=True, exist_ok=True)
    with challenge.open("w", encoding="utf-8", newline="\n") as handle:
        for conversation in load_challenge():
            row = conversation.to_dict()
            row["messages_flat"] = list(message_rows(conversation))
            row["ner"] = list(ner_rows(conversation))
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    (out_dir / "README.md").write_text(_card(manifest), encoding="utf-8")
    shutil.copyfile(dataset_dir / "manifest.json", out_dir / "manifest.json")
    return out_dir
