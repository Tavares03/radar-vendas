"""Relatório (``training/reports/<modelo>.md``) e model card (``README.md`` do Hub).

Os dois saem do mesmo JSON de avaliação, então o número do card é o do relatório.
"""

from __future__ import annotations

from typing import Any

from radar.taxonomy import CLASSIFIER_LABELS, LABELS_PT, PII_TYPES
from radar_training.metrics import is_disabled

NER_METHODS = {
    "modelo": "pii-ner-ptbr (ONNX int8)",
    "regex": "regex + validadores (produção sem modelo)",
    "regex_e_modelo": "regex + modelo (o que roda no Radar)",
    "llm_zero_shot": "LLM zero-shot",
}
CLS_METHODS = {
    "modelo": "sales-intent-ptbr (ONNX int8)",
    "regras": "regras dos playbooks",
    "tfidf": "TF-IDF + regressão logística",
    "regras_e_modelo": "regras + modelo (o que roda no Radar)",
    "llm_zero_shot": "LLM zero-shot",
}
SPLIT_NAMES = {"test": "teste", "desafio": "desafio"}
LLM_PENDING = (
    "O baseline LLM zero-shot não rodou nesta avaliação. O do classificador usa o texto mascarado e "
    "precisa de uma chave gratuita no `.env` (Groq, Gemini ou OpenRouter); o do NER recebe texto "
    "sem máscara, então só roda com Ollama local (a trava de privacidade não deixa ir para a nuvem). "
    "Rode `radar-train evaluate <modelo> --llm`."
)


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}"


def _matrix(matrix: dict[str, dict[str, int]], names: dict[str, str] | None = None) -> list[str]:
    rows = [r for r in matrix if any(matrix[r].values()) or any(matrix[o][r] for o in matrix)]
    names = names or {}
    header = "| verdadeiro ↓ / previsto → | " + " | ".join(names.get(c, c) for c in rows) + " |"
    lines = [header, "|---|" + "---:|" * len(rows)]
    for row in rows:
        cells = [str(matrix[row][c]) if matrix[row][c] else "·" for c in rows]
        lines.append(f"| {names.get(row, row)} | " + " | ".join(cells) + " |")
    return lines


# ---------------------------------------------------------------- NER
def ner_summary(evaluation: dict[str, Any]) -> list[str]:
    lines = [
        "| Conjunto | Método | Precisão | Revocação | F1 (exato) | Entidades inteiramente mascaradas |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for split, entry in evaluation["splits"].items():
        for key, name in NER_METHODS.items():
            if key not in entry:
                continue
            micro = entry[key]["exato"]["micro"]
            masked = entry[key]["mascara"]["entities_fully_masked"]
            lines.append(
                f"| {SPLIT_NAMES[split]} ({entry['entidades']} entidades) | {name} | {pct(micro['precision'])} | "
                f"{pct(micro['recall'])} | **{pct(micro['f1'])}** | {pct(masked)} |"
            )
    return lines


def ner_per_type(entry: dict[str, Any]) -> list[str]:
    model, regex = entry["modelo"], entry["regex"]
    lines = [
        "| Tipo | Suporte | Precisão | Revocação | F1 | F1 regex | Mascarado (modelo) | Mascarado (regex) | Mascarado (regex + modelo) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for kind in PII_TYPES:
        score = model["exato"]["per_class"].get(kind)
        if not score or not score["support"]:
            continue
        lines.append(
            f"| {kind} | {score['support']} | {pct(score['precision'])} | {pct(score['recall'])} | "
            f"**{pct(score['f1'])}** | {pct(regex['exato']['per_class'][kind]['f1'])} | "
            f"{pct(model['mascara']['per_type'][kind])} | {pct(regex['mascara']['per_type'][kind])} | "
            f"{pct(entry['regex_e_modelo']['mascara']['per_type'][kind])} |"
        )
    return lines


# ---------------------------------------------------------------- classificador
def cls_summary(evaluation: dict[str, Any]) -> list[str]:
    lines = [
        "| Conjunto | Método | Precisão (micro) | Revocação (micro) | F1 micro | F1 macro |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for split, entry in evaluation["splits"].items():
        for key, name in CLS_METHODS.items():
            if key not in entry:
                continue
            metrics = entry[key]["metricas"]
            micro = metrics["micro"]
            lines.append(
                f"| {SPLIT_NAMES[split]} ({entry['mensagens']} mensagens) | {name} | {pct(micro['precision'])} | "
                f"{pct(micro['recall'])} | **{pct(micro['f1'])}** | {pct(metrics['macro_f1'])} |"
            )
    return lines


def _threshold(value: float) -> str:
    return "desligado" if is_disabled(value) else f"{value:.2f}"


def disabled_note(thresholds: dict[str, float], min_precision: float | None) -> list[str]:
    """Explica os rótulos que o treino desligou por não serem confiáveis o bastante."""
    off = [label for label in CLASSIFIER_LABELS if is_disabled(thresholds.get(label, 0.5))]
    if not off:
        return []
    floor = f"{min_precision:.2f}".replace(".", ",") if min_precision else "mínima"
    names = ", ".join(f"{LABELS_PT.get(label, label).lower()}" for label in off)
    return [
        f"**Rótulos desligados:** {names}. Em nenhum limiar o modelo alcançou precisão {floor} "
        "neles na validação, então em produção ele não os aponta: esses casos ficam com as regras "
        "do playbook e com o LLM. Um alerta apontado só pelo modelo precisa ser confiável.",
        "",
    ]


def cls_per_label(entry: dict[str, Any], thresholds: dict[str, float]) -> list[str]:
    lines = [
        "| Rótulo | Suporte | Limiar | Precisão | Revocação | F1 | F1 regras | F1 TF-IDF |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label in CLASSIFIER_LABELS:
        score = entry["modelo"]["metricas"]["per_class"][label]
        lines.append(
            f"| {LABELS_PT.get(label, label)} (`{label}`) | {score['support']} | {_threshold(thresholds.get(label, 0.5))} | "
            f"{pct(score['precision'])} | {pct(score['recall'])} | **{pct(score['f1'])}** | "
            f"{pct(entry['regras']['metricas']['per_class'][label]['f1'])} | "
            f"{pct(entry['tfidf']['metricas']['per_class'][label]['f1']) if 'tfidf' in entry else '—'} |"
        )
    return lines


# ---------------------------------------------------------------- comuns
def runtime_lines(evaluation: dict[str, Any]) -> list[str]:
    latency, size, parity = evaluation["latencia"], evaluation["tamanho_mb"], evaluation["paridade"]
    lines = [
        "| Versão | Tamanho (MB) | Uma mensagem, p50 (ms) | p95 (ms) | Lotes de 32 (mensagens/s) |",
        "|---|---:|---:|---:|---:|",
    ]
    for key in ("int8", "fp32"):
        lines.append(
            f"| ONNX {key} | {size[key]} | {latency[key]['p50_ms']} | {latency[key]['p95_ms']} | "
            f"{latency[key]['messages_per_second']} |"
        )
    lines += ["", "Paridade (validação, " + str(parity["mensagens"]) + " mensagens):", ""]
    for key, value in parity.items():
        if key == "mensagens":
            continue
        label = key.replace("_x_", " × ").replace("_", " ")
        shown = f"{value * 100:.2f}% iguais" if "dif" not in key else f"{value}"
        lines.append(f"- {label}: {shown}")
    return lines


def quantization_lines(training: dict[str, Any]) -> list[str]:
    """Como o modelo foi quantizado e quanto isso custou na validação (se o treino registrou)."""
    info = training.get("quantizacao")
    if not info:
        return []
    lines = [""]
    if "metrica_fp32" in info:
        verdict = (
            f"Quantização: **{info['receita']}**. Na validação, a métrica do treino ficou em "
            f"{info['metrica_quantizado']:.4f} no modelo quantizado contra {info['metrica_fp32']:.4f} "
            f"no fp32 (tolerância: {info['tolerancia']})."
        )
        if not info["aprovado"]:
            verdict += (
                " **Nenhuma receita ficou dentro da tolerância: o manifesto aponta para o fp32** e é "
                "ele que o runtime carrega."
            )
        lines.append(verdict)
    else:
        lines.append(f"Quantização: **{info['receita']}** (sem conferência de qualidade).")
    rejected = [a for a in info.get("tentativas", []) if a["receita"] != info["receita"]]
    if rejected:
        lines.append(
            "Receitas medidas e descartadas: "
            + "; ".join(f"{a['receita']} ({a.get('metrica', 0):.4f})" for a in rejected)
            + "."
        )
    return lines


def training_lines(training: dict[str, Any]) -> list[str]:
    config = training["config"]
    lines = [
        f"- Base: `{config['base_model']}`; semente {config['seed']}; até {config['epochs']} épocas "
        f"(parada antecipada com paciência {config['patience']}); lote {config['batch_size']}; "
        f"taxa {config['learning_rate']}; aquecimento {config['warmup_ratio']}; máximo {config['max_length']} tokens.",
        f"- Melhor época: {training['best_epoch']} (validação {training['best_score']:.4f}); "
        f"tempo total {training['seconds'] / 60:.1f} min em {training['hardware']}.",
        "",
        "| Época | Perda | Validação |",
        "|---:|---:|---:|",
    ]
    lines += [f"| {h['epoch']} | {h['loss']:.4f} | {h['score']:.4f} |" for h in training["history"]]
    return lines


def render_report(report: dict[str, Any]) -> str:
    model, evaluation = report["modelo"], report["avaliacao"]
    ner = model["task"] == "ner"
    out = [
        f"# {model['name']} {model['version']}",
        "",
        f"Base `{model['base_model']}`, dataset `{model['dataset_version']}`. Métricas do modelo "
        "exportado (ONNX int8) rodando pelo runtime de produção (`radar.ml`).",
        "",
        "> O conjunto de **teste** é sintético como o treino, mas com famílias de template que o treino "
        "nunca viu: mede generalização entre templates. O **desafio** tem casos difíceis escritos à mão "
        "e é pequeno. Nenhum dos dois substitui dados reais; veja as limitações no model card.",
        "",
        "## Resumo",
        "",
        *(ner_summary(evaluation) if ner else cls_summary(evaluation)),
        "",
    ]
    if not any("llm_zero_shot" in e for e in evaluation["splits"].values()):
        out += [LLM_PENDING, ""]
    test = evaluation["splits"]["test"]
    if ner:
        out += [
            "## Por tipo (teste)",
            "",
            *ner_per_type(test),
            "",
            "## Matriz de confusão (teste, modelo)",
            "",
        ]
        out += _matrix(test["modelo"]["confusao"])
    else:
        out += ["## Por rótulo (teste)", "", *cls_per_label(test, evaluation["limiares"]), ""]
        out += disabled_note(
            evaluation["limiares"], report["treino"].get("config", {}).get("min_precision")
        )
        out += [
            "## Matriz de confusão (teste, modelo)",
            "",
            "Linha = rótulo verdadeiro; coluna = o que o modelo disse.",
            "",
        ]
        out += _matrix(test["modelo"]["confusao"])
    out += ["", "## CPU, tamanho e paridade", "", *runtime_lines(evaluation)]
    out += [*quantization_lines(report["treino"]), ""]
    out += ["## Treino", "", *training_lines(report["treino"]), ""]
    return "\n".join(out)


# ---------------------------------------------------------------- model card
def render_card(report: dict[str, Any], *, repo_id: str, dataset_id: str) -> str:
    model, evaluation = report["modelo"], report["avaliacao"]
    ner = model["task"] == "ner"
    tags = (
        ["token-classification", "ner", "pii", "lgpd", "anonymization"]
        if ner
        else ["text-classification", "multi-label-classification", "sales", "compliance"]
    )
    front = [
        "---",
        "language:",
        "- pt",
        "license: apache-2.0",
        "library_name: transformers",
        f"pipeline_tag: {'token-classification' if ner else 'text-classification'}",
        f"base_model: {model['base_model']}",
        "datasets:",
        f"- {dataset_id}",
        "metrics:",
        "- precision",
        "- recall",
        "- f1",
        "tags:",
        *[
            f"- {t}"
            for t in [
                *tags,
                "portuguese",
                "brazilian-portuguese",
                "whatsapp",
                "onnx",
                "synthetic-data",
            ]
        ],
        "---",
        "",
    ]
    body = _card_body_ner(report, repo_id) if ner else _card_body_classifier(report, repo_id)
    return "\n".join(front + body + _card_common(report, dataset_id, evaluation))


def _card_body_ner(report: dict[str, Any], repo_id: str) -> list[str]:
    model = report["modelo"]
    return [
        f"# {model['name']}",
        "",
        "NER de **dados pessoais em português do Brasil**, feito para mensagens informais (WhatsApp): "
        "abreviações, erros de digitação, números sem formatação e áudios transcritos. Encontra "
        + ", ".join(f"`{t}`" for t in PII_TYPES)
        + ".",
        "",
        "Faz parte do [Radar de Vendas](https://github.com/Tavares03/radar-vendas), onde mascara as conversas "
        "antes de qualquer análise (LGPD). Funciona sozinho em qualquer projeto que precise anonimizar texto em PT-BR.",
        "",
        "## Como usar",
        "",
        "```python",
        "from transformers import pipeline",
        "",
        f'ner = pipeline("token-classification", model="{repo_id}", aggregation_strategy="simple")',
        'ner("Oi, sou a Mariana Souza, meu CPF é 529.982.247-25 e o pix é mariana@exemplo.com")',
        "```",
        "",
        "Em CPU, sem PyTorch, use o ONNX quantizado (`onnx/model_quantized.onnx`) com `onnxruntime` e "
        "`tokenizers`; o rótulo de cada token sai em BIO (`O`, `B-CPF`, `I-CPF`…). O Radar faz isso em "
        "[`radar/ml/ner.py`](https://github.com/Tavares03/radar-vendas/blob/main/backend/src/radar/ml/ner.py), "
        "inclusive janelas para textos longos.",
        "",
        "## Uso pretendido",
        "",
        "- Mascarar dado pessoal antes de guardar, indexar ou mandar texto para um LLM.",
        "- Camada **somada** a regras e validadores (CPF, CNPJ e telefone têm dígitos verificadores e formato; "
        "use os dois). No Radar, o modelo entra junto com regex e os nomes dos participantes da conversa.",
        "",
        "Não use como única proteção de dados sensíveis sem medir no seu próprio texto.",
        "",
    ]


def _card_body_classifier(report: dict[str, Any], repo_id: str) -> list[str]:
    model = report["modelo"]
    labels = ", ".join(f"`{label}`" for label in CLASSIFIER_LABELS)
    return [
        f"# {model['name']}",
        "",
        "Classificador **multirrótulo** de mensagens de venda em português do Brasil (WhatsApp). Para mensagens "
        "do vendedor, aponta riscos de compliance (promessa indevida, informação enganosa, pressão abusiva, "
        "pagamento fora do canal, linguagem inadequada, pedido indevido de dado pessoal); para mensagens do "
        "cliente, objeções, sinal de compra e pedidos.",
        "",
        f"Rótulos: {labels}.",
        "",
        "## Como usar",
        "",
        "A entrada é o par (papel de quem escreveu, texto **mascarado**). Dados pessoais devem estar trocados "
        "por marcadores como `[CPF]` e `[TELEFONE]`, como no treino.",
        "",
        "```python",
        "import torch",
        "from transformers import AutoModelForSequenceClassification, AutoTokenizer",
        "",
        f'tokenizer = AutoTokenizer.from_pretrained("{repo_id}")',
        f'model = AutoModelForSequenceClassification.from_pretrained("{repo_id}")',
        'inputs = tokenizer("vendedor", "Pode fazer o pix direto na minha conta pessoal", return_tensors="pt")',
        "probabilities = torch.sigmoid(model(**inputs).logits)[0]",
        "print({model.config.id2label[i]: round(float(p), 3) for i, p in enumerate(probabilities)})",
        "```",
        "",
        "Os limiares por rótulo, calibrados na validação, estão em `radar_model.json` (`thresholds`). Rótulos "
        "de vendedor só valem em mensagens do vendedor, e os de cliente, nas do cliente. Um limiar acima de 1 "
        "quer dizer que o rótulo está **desligado**: o modelo não alcançou a precisão mínima nele na validação "
        "(veja a tabela por rótulo) e é melhor não apontar do que apontar errado.",
        "",
        "## Uso pretendido",
        "",
        "- Apontar mensagens para **revisão humana** (fila de alertas), junto com regras auditáveis e um LLM "
        "que confirma ou contesta. No Radar, achado só do classificador e contestado pelo LLM é descartado.",
        "- Não use para punir ou avaliar pessoas automaticamente.",
        "",
    ]


def _card_common(report: dict[str, Any], dataset_id: str, evaluation: dict[str, Any]) -> list[str]:
    ner = report["modelo"]["task"] == "ner"
    lines = [
        "## Avaliação",
        "",
        "Modelo exportado (ONNX int8) avaliado pelo mesmo código que roda em produção.",
        "",
        *(ner_summary(evaluation) if ner else cls_summary(evaluation)),
        "",
    ]
    if not any("llm_zero_shot" in e for e in evaluation["splits"].values()):
        lines += [LLM_PENDING, ""]
    test = evaluation["splits"]["test"]
    lines += ["### Por tipo (teste)" if ner else "### Por rótulo (teste)", ""]
    lines += ner_per_type(test) if ner else cls_per_label(test, evaluation["limiares"])
    lines += [
        "",
        "Relatório completo, com matriz de confusão e paridade: "
        f"[`training/reports/{report['modelo']['name']}.md`](https://github.com/Tavares03/radar-vendas/blob/main/training/reports/{report['modelo']['name']}.md).",
        "",
        "### CPU",
        "",
        *runtime_lines(evaluation),
        "",
        "## Dados de treino",
        "",
        f"Treinado **só com dados sintéticos** ([`{dataset_id}`](https://huggingface.co/datasets/{dataset_id}), "
        f"versão `{report['modelo']['dataset_version']}`): conversas de venda geradas por templates com ruído de "
        "WhatsApp, em consórcio, seguros, imobiliária, clínica e varejo, com anotação por construção. Nenhuma "
        "pessoa ou empresa real. Os conjuntos de validação e teste usam famílias de template separadas das do treino.",
        "",
        "## Limitações e vieses",
        "",
        "- **Sintético**: o modelo nunca viu conversa real. O teste mede generalização entre templates do mesmo "
        "gerador; em texto real, espere números menores. Meça no seu texto antes de confiar.",
        "- O vocabulário, os nomes e os endereços vêm de listas do gerador: nomes e regiões pouco representados "
        "nelas tendem a ser menos reconhecidos.",
        "- Cinco setores; outros setores e outros registros (e-mail formal, atendimento técnico) não foram medidos.",
        "- Textos muito longos são lidos em janelas de "
        + str(report["treino"]["config"]["max_length"])
        + " tokens.",
    ]
    if ner:
        lines.append(
            '- Números sem contexto ("me liga no 11 9..." partido em várias mensagens) podem escapar; '
            "combine com regras e validadores."
        )
    else:
        lines.append(
            '- Rótulos dependem do contexto da conversa (uma "objeção sem resposta" só existe olhando as '
            "mensagens seguintes): o classificador olha uma mensagem por vez; o Radar junta o resto."
        )
    lines += [
        "",
        "## Treino",
        "",
        *training_lines(report["treino"]),
        "",
        "Código, configuração e semente: [`training/`](https://github.com/Tavares03/radar-vendas/tree/main/training) "
        f"(`radar-train run {report['modelo']['name']}`).",
        "",
        "## Licença",
        "",
        f"Apache-2.0. Base `{report['modelo']['base_model']}` sob licença "
        f"{report['treino']['config'].get('base_license', 'MIT')}.",
        "",
    ]
    return lines
