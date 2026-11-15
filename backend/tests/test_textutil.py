"""Textos que o painel mostra: plural certo e duração como as pessoas falam."""

from __future__ import annotations

import pytest

from radar.textutil import duration_pt, fold, plural


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, "0 objeções"), (1, "1 objeção"), (2, "2 objeções"), (21, "21 objeções")],
)
def test_plural(count: int, expected: str):
    assert plural(count, "objeção", "objeções") == expected


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (0, "0 min"),
        (45, "45 min"),
        (59.6, "1 h"),
        (60, "1 h"),
        (561, "9 h 21 min"),
        (47 * 60 + 59, "47 h 59 min"),
        (48 * 60, "2 dias"),
        (5 * 24 * 60, "5 dias"),
    ],
)
def test_duracao(minutes: float, expected: str):
    assert duration_pt(minutes) == expected


def test_fold_mantem_o_comprimento():
    assert fold("Contemplação GARANTIDA") == "contemplacao garantida"
    assert len(fold("São João")) == len("São João")
