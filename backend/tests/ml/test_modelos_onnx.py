"""Runtime dos modelos próprios (ONNX, sem PyTorch): decodificação, NER, classificador e carga."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from radar.analysis import analyze_conversation
from radar.analysis.models import ConversationInput, MessageInput
from radar.config import Settings
from radar.ml import loader
from radar.ml.classifier import OnnxMessageClassifier, classifier_pair
from radar.ml.ner import NER_LABELS, OnnxPiiNer, decode_bio, token_labels
from radar.playbooks import load_playbook
from radar.privacy.detector import PiiDetector
from radar.taxonomy import PiiType, SenderRole
from radar.tenant_settings import BusinessHours

LABELS = list(NER_LABELS)


def probs(*labels: str) -> np.ndarray:
    rows = np.full((len(labels), len(LABELS)), 0.01, dtype=np.float32)
    for row, label in zip(rows, labels, strict=True):
        row[LABELS.index(label)] = 0.9
    return rows


@pytest.fixture(autouse=True)
def _sem_cache() -> Iterator[None]:
    loader.clear_cache()
    yield
    loader.clear_cache()


# ---------------------------------------------------------------- rótulos e decodificação
def test_rotulos_bio_marcam_o_primeiro_token_da_entidade_e_ignoram_especiais():
    # [CLS] "Joana" "Silva" "ligou" [SEP]
    offsets = [(0, 0), (0, 5), (6, 11), (12, 17), (0, 0)]
    special = [1, 0, 0, 0, 1]
    labels = token_labels(offsets, special, [("NOME_PESSOA", 0, 11)])
    assert labels == [None, "B-NOME_PESSOA", "I-NOME_PESSOA", "O", None]


def test_rotulo_vale_para_token_que_so_encosta_em_parte_da_entidade():
    # Tokenizadores SentencePiece incluem o espaço antes da palavra no token.
    offsets = [(0, 3), (3, 9)]
    labels = token_labels(offsets, [0, 0], [("NOME_PESSOA", 4, 9)])
    assert labels == ["O", "B-NOME_PESSOA"]


def test_decodificacao_junta_b_e_i_e_corta_espacos():
    text = "oi joana silva!"
    offsets = [(0, 2), (2, 8), (8, 14), (14, 15)]
    spans = decode_bio(
        text, offsets, [0, 0, 0, 0], probs("O", "B-NOME_PESSOA", "I-NOME_PESSOA", "O"), LABELS
    )
    assert [(s.type, text[s.start : s.end]) for s in spans] == [("NOME_PESSOA", "joana silva")]
    assert spans[0].score == pytest.approx(0.9)


def test_pedaco_de_palavra_rotulado_b_continua_o_trecho():
    text = "cpf 12345678909"
    offsets = [(4, 9), (9, 15)]
    spans = decode_bio(text, offsets, [0, 0], probs("B-CPF", "B-CPF"), LABELS)
    assert [(s.start, s.end) for s in spans] == [(4, 15)]


def test_trecho_cresce_ate_a_palavra_inteira_para_nao_sobrar_meio_nome():
    text = "fala com Mariana"
    # O modelo só rotulou o primeiro pedaço ("Mari"); o resto da palavra entra na máscara.
    offsets = [(0, 4), (5, 8), (9, 13), (13, 16)]
    spans = decode_bio(text, offsets, [0, 0, 0, 0], probs("O", "O", "B-NOME_PESSOA", "O"), LABELS)
    assert [text[s.start : s.end] for s in spans] == ["Mariana"]


def test_tipos_diferentes_lado_a_lado_viram_trechos_separados():
    text = "ana 11999998888"
    offsets = [(0, 3), (4, 15)]
    spans = decode_bio(text, offsets, [0, 0], probs("B-NOME_PESSOA", "B-TELEFONE"), LABELS)
    assert [(s.type, s.start, s.end) for s in spans] == [("NOME_PESSOA", 0, 3), ("TELEFONE", 4, 15)]


# ---------------------------------------------------------------- NER em ONNX
def test_ner_acha_nome_com_posicao_no_texto_original(make_ner_model: Callable[..., Path]):
    ner = OnnxPiiNer(make_ner_model())
    text = "Oi, meu nome é Joana Silva."
    [spans] = ner.predict([text])
    assert [(s.type, s.text, s.source) for s in spans] == [
        (PiiType.NOME_PESSOA, "Joana Silva", "ner")
    ]
    assert text[spans[0].start : spans[0].end] == "Joana Silva"
    assert ner.name == "ner-teste@1.0"


def test_ner_processa_lote_com_texto_vazio_e_sem_entidade(make_ner_model: Callable[..., Path]):
    ner = OnnxPiiNer(make_ner_model())
    result = ner.predict(["", "tudo bem", "joana"])
    assert [[s.text for s in spans] for spans in result] == [[], [], ["joana"]]


def test_ner_le_texto_longo_em_janelas_sobrepostas(make_ner_model: Callable[..., Path]):
    ner = OnnxPiiNer(make_ner_model(max_length=8, stride=2))
    text = "oi tudo bem " * 6 + "meu nome e joana silva"
    [spans] = ner.predict([text])
    assert [(s.text, s.start) for s in spans] == [("joana silva", text.index("joana"))]


def test_detector_usa_o_ner_para_mascarar(make_ner_model: Callable[..., Path]):
    detector = PiiDetector(ner=OnnxPiiNer(make_ner_model()))
    masked = detector.mask("meu nome é Joana Silva, cpf 529.982.247-25")
    assert masked.text == "meu nome é [NOME_PESSOA], cpf [CPF]"
    assert "ner:ner-teste@1.0" in detector.layers


def test_modelo_com_tipo_desconhecido_e_recusado(make_ner_model: Callable[..., Path]):
    path = make_ner_model(labels=["O", "B-SENHA", "I-SENHA"])
    with pytest.raises(ValueError, match="SENHA"):
        OnnxPiiNer(path)


def test_ner_recusa_pasta_de_classificador(make_classifier_model: Callable[..., Path]):
    with pytest.raises(ValueError, match="não é um modelo de NER"):
        OnnxPiiNer(make_classifier_model())


# ---------------------------------------------------------------- classificador em ONNX
def message(index: int, sender: SenderRole, text: str) -> MessageInput:
    return MessageInput(index, sender, text, datetime(2025, 3, 11, 13, index, tzinfo=UTC))


def test_classificador_devolve_probabilidade_por_rotulo(make_classifier_model: Callable[..., Path]):
    model = OnnxMessageClassifier(make_classifier_model(thresholds={"objecao_preco": 0.7}))
    result = model.predict(
        [
            message(0, SenderRole.VENDEDOR, "pode pagar no pix"),
            message(1, SenderRole.CLIENTE, "achei caro"),
            message(2, SenderRole.CLIENTE, "   "),
        ]
    )
    assert result[0]["pagamento_fora_canal"] > 0.9
    assert 0.5 < result[1]["objecao_preco"] < 0.7
    assert result[2] == {}
    # Limiar do manifesto; o que faltar fica em 0,5.
    assert model.thresholds == {
        "pagamento_fora_canal": 0.5,
        "objecao_preco": 0.7,
        "sinal_compra": 0.5,
    }


def test_entrada_do_classificador_e_o_par_papel_e_texto():
    assert classifier_pair(SenderRole.CLIENTE, "achei caro") == ("cliente", "achei caro")
    assert classifier_pair("vendedor", "oi") == ("vendedor", "oi")


def test_classificador_vira_camada_da_analise(make_classifier_model: Callable[..., Path]):
    model = OnnxMessageClassifier(make_classifier_model())
    messages = [
        message(0, SenderRole.CLIENTE, "oi tudo bem"),
        message(1, SenderRole.VENDEDOR, "pode pagar no pix"),
        # Rótulo de vendedor em mensagem do cliente não conta.
        message(2, SenderRole.CLIENTE, "pix"),
    ]
    conversation = ConversationInput(
        messages=messages,
        playbook=load_playbook("generico"),
        timezone=ZoneInfo("America/Sao_Paulo"),
        business_hours=BusinessHours(),
        reference_time=datetime(2025, 3, 11, 14, 0, tzinfo=UTC),
    )
    analysis = analyze_conversation(conversation, classifier=model)
    assert "classificador" in analysis.layers
    found = [f for f in analysis.findings if f.type == "pagamento_fora_canal"]
    assert [f.message_index for f in found] == [1]
    assert found[0].sources["classificador"]["modelo"] == "classificador-teste@1.0"


# ---------------------------------------------------------------- onde achar o modelo
def settings_for(tmp_path: Path, **values: object) -> Settings:
    return Settings(
        _env_file=None, models_dir=tmp_path / "models", data_dir=tmp_path / "data", **values
    )  # type: ignore[call-arg]


def test_off_desliga_e_auto_sem_modelo_deixa_a_camada_de_fora(tmp_path: Path):
    assert loader.load_ner(settings_for(tmp_path, ner_model="off")) is None
    assert loader.load_ner(settings_for(tmp_path, ner_model="auto")) is None
    assert loader.load_classifier(settings_for(tmp_path, classifier_model="auto")) is None


def test_auto_usa_a_pasta_de_modelos_e_carrega_uma_vez(
    tmp_path: Path, make_ner_model: Callable[..., Path], make_classifier_model: Callable[..., Path]
):
    make_ner_model(tmp_path / "models" / loader.NER_NAME)
    make_classifier_model(tmp_path / "models" / loader.CLASSIFIER_NAME)
    settings = settings_for(tmp_path, ner_model="auto", classifier_model="auto")
    ner = loader.load_ner(settings)
    assert ner is not None
    assert ner.name == "ner-teste@1.0"
    assert loader.load_ner(settings) is ner
    classifier = loader.load_classifier(settings)
    assert classifier is not None
    assert classifier.name == "classificador-teste@1.0"


def test_caminho_explicito(tmp_path: Path, make_ner_model: Callable[..., Path]):
    path = make_ner_model(tmp_path / "outro-lugar")
    ner = loader.load_ner(settings_for(tmp_path, ner_model=str(path)))
    assert ner is not None


def test_id_do_hub_baixa_so_o_que_o_runtime_usa(
    tmp_path: Path, make_ner_model: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
):
    published = make_ner_model(tmp_path / "hub")
    calls: list[tuple[str, list[str]]] = []

    def fake_download(repo_id: str, *, allow_patterns: list[str], local_dir: Path) -> str:
        calls.append((repo_id, allow_patterns))
        return str(published)

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_download)
    settings = settings_for(tmp_path, ner_model="auto", ner_hub_id="alguem/pii-ner-ptbr")
    assert loader.load_ner(settings) is not None
    assert calls == [("alguem/pii-ner-ptbr", list(loader.RUNTIME_FILES))]


def test_id_do_hub_baixa_o_onnx_que_o_manifesto_aponta(
    tmp_path: Path, make_ner_model: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
):
    """Quantização reprovada no treino: o manifesto aponta para o fp32, que não é baixado por padrão."""
    published = make_ner_model(tmp_path / "hub")
    manifest = json.loads((published / "radar_model.json").read_text(encoding="utf-8"))
    manifest["onnx"] = "onnx/model.onnx"
    (published / "radar_model.json").write_text(json.dumps(manifest), encoding="utf-8")
    hidden = published / "onnx" / "model.onnx"
    parked = tmp_path / "ainda-no-hub.onnx"
    hidden.replace(parked)
    calls: list[list[str]] = []

    def fake_download(repo_id: str, *, allow_patterns: list[str], local_dir: Path) -> str:
        calls.append(allow_patterns)
        if allow_patterns == ["onnx/model.onnx"]:
            parked.replace(hidden)
        return str(published)

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_download)
    settings = settings_for(tmp_path, ner_model="auto", ner_hub_id="alguem/pii-ner-ptbr")
    assert loader.load_ner(settings) is not None
    assert calls == [list(loader.RUNTIME_FILES), ["onnx/model.onnx"]]


def test_modelo_quebrado_nao_derruba_nada(tmp_path: Path, make_ner_model: Callable[..., Path]):
    path = make_ner_model(tmp_path / "models" / loader.NER_NAME)
    (path / "radar_model.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    assert loader.load_ner(settings_for(tmp_path, ner_model="auto")) is None
    missing = settings_for(tmp_path, ner_model=str(tmp_path / "nao-existe"))
    assert loader.load_ner(missing) is None


def test_comando_models_mostra_o_que_esta_em_uso(
    tmp_path: Path, make_ner_model: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
):
    from typer.testing import CliRunner

    from radar.cli import app
    from radar.config import get_settings

    make_ner_model(tmp_path / "models" / loader.NER_NAME)
    monkeypatch.setenv("RADAR_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("RADAR_NER_MODEL", "auto")
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["models"])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0, result.output
    assert "NER de dados pessoais: ner-teste@1.0" in result.output
    assert "Classificador de mensagens: desligado [off]" in result.output
