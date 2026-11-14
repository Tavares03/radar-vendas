"""Renderização de templates e ruído de WhatsApp sem estragar as anotações."""

from __future__ import annotations

import random

import pytest

from radar.privacy.validators import is_valid_cpf
from radar.taxonomy import PiiType
from radar_synth.banks import load_bank
from radar_synth.noise import abbreviate, add_typo, apply_noise
from radar_synth.render import MessageStyle, Persona, Renderer, SlotContext


def _renderer(seed: int = 1, sector: str = "consorcio") -> Renderer:
    rng = random.Random(seed)
    context = SlotContext.create(rng, load_bank(sector))
    return Renderer(load_bank(sector), rng, context)


def test_slots_de_dado_pessoal_viram_trechos_anotados():
    renderer = _renderer()
    (part,) = renderer.render("Meu CPF é {cpf} e o email {email}", MessageStyle())

    types = [span.type for span in part.spans]
    assert types == [PiiType.CPF, PiiType.EMAIL]
    for span in part.spans:
        assert part.text[span.start : span.end] == span.value
    assert is_valid_cpf(part.spans[0].value)


def test_o_mesmo_cliente_tem_o_mesmo_cpf_na_conversa_toda():
    renderer = _renderer()
    first = renderer.render("{cpf}", MessageStyle())[0].spans[0].value
    second = renderer.render("cpf: {cpf}", MessageStyle())[0].spans[0].value
    assert first.replace(".", "").replace("-", "") == second.replace(".", "").replace("-", "")


def test_vocabulario_do_setor_fica_fixo_na_conversa():
    renderer = _renderer()
    produtos = {renderer.render("{produto}", MessageStyle())[0].text for _ in range(10)}
    assert len(produtos) == 1


def test_mensagem_picotada_vira_varias_partes():
    renderer = _renderer()
    parts = renderer.render(
        "Oi || tudo bem? || queria saber do {produto}", MessageStyle(split=True)
    )
    assert [p.text.split()[0] for p in parts] == ["Oi", "tudo", "queria"]
    joined = renderer.render("Oi || tudo bem?", MessageStyle(split=False))
    assert len(joined) == 1
    assert "||" not in joined[0].text


@pytest.mark.parametrize("seed", range(30))
def test_ruido_pesado_nunca_estraga_os_trechos(seed: int):
    renderer = _renderer(seed)
    style = MessageStyle(noise=3, lowercase_names=True, emoji=True)
    template = (
        "Oi {primeiro_nome_vendedor}, você também precisa do meu cpf {cpf}? meu email é {email}"
    )
    for part in renderer.render(template, style):
        for span in part.spans:
            assert part.text[span.start : span.end] == span.value
            if span.type is PiiType.NOME_PESSOA:
                assert span.value == span.value.lower()


def test_artigo_concorda_com_o_genero_do_nome():
    rng = random.Random(3)
    context = SlotContext.create(rng, load_bank("consorcio"))
    context.seller = Persona.build(rng, gender="F")
    renderer = Renderer(load_bank("consorcio"), rng, context)
    (part,) = renderer.render("Sou o {primeiro_nome_vendedor} da {empresa}", MessageStyle())
    assert part.text.startswith("Sou a ")


def test_estilo_de_audio_nao_tem_emoji_nem_abreviacao():
    renderer = _renderer(5)
    style = MessageStyle(noise=3, audio=True, emoji=True)
    (part,) = renderer.render("Você também quer saber do {produto} porque precisa?", style)
    assert "vc" not in part.text.split()
    assert not any(ord(ch) > 0x2600 for ch in part.text)


# ---------------------------------------------------------------- ruído
def test_abreviacoes_comuns():
    rng = random.Random(0)
    assert abbreviate("Você também está aqui porque quer", rng, probability=1.0) in {
        "vc tb tá aqui pq quer",
        "vc tbm tá aqui pq quer",
        "vc tb ta aqui pq quer",
        "vc tbm ta aqui pq quer",
    }


def test_abreviacao_respeita_palavra_inteira():
    rng = random.Random(0)
    assert abbreviate("parabéns, paralelo", rng, probability=1.0) == "parabéns, paralelo"


def test_erro_de_digitacao_muda_pouco():
    rng = random.Random(4)
    for _ in range(50):
        word = add_typo("garantido", rng)
        assert abs(len(word) - len("garantido")) <= 1
        assert word != ""
        assert word[0] == "g"


def test_sem_ruido_o_texto_fica_igual():
    rng = random.Random(1)
    assert apply_noise("Bom dia, tudo bem?", rng, level=0) == "Bom dia, tudo bem?"
