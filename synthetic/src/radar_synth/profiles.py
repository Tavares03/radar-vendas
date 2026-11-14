"""Perfis de vendedor e de cliente: as probabilidades que dão forma a cada roteiro."""

from __future__ import annotations

from dataclasses import dataclass

from radar.taxonomy import Outcome


@dataclass(frozen=True, slots=True)
class SellerProfile:
    name: str
    #: Explica as condições obrigatórias do setor depois de apresentar o produto.
    disclose: float
    #: Dá informação enganosa na apresentação.
    misleading: float
    #: Promete o que não pode quando o cliente pergunta se é garantido.
    promise_on_guarantee: float
    #: Atende um pedido do cliente (simulação, documento).
    answer_request: float
    #: Como trata objeções: pesos de ``bem``, ``parcial``, ``mal`` e ``sem_resposta``.
    handling: tuple[float, float, float, float]
    improper_data: float
    off_channel: float
    rude_on_loss: float
    follow_up: float
    close_on_signal: float
    #: Minutos até responder (faixa típica) e chance de demorar horas.
    reply_minutes: tuple[float, float]
    slow_reply: float
    noise: tuple[int, int]


SELLER_PROFILES: dict[str, SellerProfile] = {
    "bom": SellerProfile(
        name="bom",
        disclose=0.8,
        misleading=0.0,
        promise_on_guarantee=0.0,
        answer_request=0.97,
        handling=(0.85, 0.15, 0.0, 0.0),
        improper_data=0.0,
        off_channel=0.0,
        rude_on_loss=0.0,
        follow_up=0.9,
        close_on_signal=1.0,
        reply_minutes=(1, 12),
        slow_reply=0.02,
        noise=(0, 1),
    ),
    "medio": SellerProfile(
        name="medio",
        disclose=0.35,
        misleading=0.08,
        promise_on_guarantee=0.15,
        answer_request=0.65,
        handling=(0.3, 0.4, 0.05, 0.25),
        improper_data=0.05,
        off_channel=0.05,
        rude_on_loss=0.05,
        follow_up=0.45,
        close_on_signal=0.8,
        reply_minutes=(3, 45),
        slow_reply=0.15,
        noise=(1, 2),
    ),
    "problematico": SellerProfile(
        name="problematico",
        disclose=0.05,
        misleading=0.4,
        promise_on_guarantee=0.8,
        answer_request=0.5,
        handling=(0.05, 0.3, 0.45, 0.2),
        improper_data=0.3,
        off_channel=0.5,
        rude_on_loss=0.4,
        follow_up=0.1,
        close_on_signal=0.4,
        reply_minutes=(3, 90),
        slow_reply=0.3,
        noise=(1, 3),
    ),
}


@dataclass(frozen=True, slots=True)
class CustomerProfile:
    name: str
    #: Objeções que este cliente tende a levantar (sorteadas sem repetição).
    objections: tuple[str, ...]
    n_objections: tuple[int, int]
    asks_guarantee: float
    #: Chance de mandar mensagens picotadas, áudio e nomes em minúsculas.
    split_messages: float
    audio: float
    lowercase_names: float
    hard_negative: float
    noise: tuple[int, int]
    outcome_weights: dict[str, float]


CUSTOMER_PROFILES: dict[str, CustomerProfile] = {
    "decidido": CustomerProfile(
        name="decidido",
        objections=("preco", "prazo", "cancelamento"),
        n_objections=(0, 1),
        asks_guarantee=0.3,
        split_messages=0.2,
        audio=0.1,
        lowercase_names=0.3,
        hard_negative=0.4,
        noise=(1, 2),
        outcome_weights={
            Outcome.GANHA: 0.7,
            Outcome.PERDIDA: 0.05,
            Outcome.EM_ANDAMENTO: 0.15,
            Outcome.ESFRIOU: 0.1,
        },
    ),
    "pesquisador": CustomerProfile(
        name="pesquisador",
        objections=("concorrente", "preco", "cancelamento", "prazo"),
        n_objections=(1, 3),
        asks_guarantee=0.5,
        split_messages=0.1,
        audio=0.05,
        lowercase_names=0.1,
        hard_negative=0.3,
        noise=(0, 1),
        outcome_weights={
            Outcome.GANHA: 0.3,
            Outcome.PERDIDA: 0.3,
            Outcome.EM_ANDAMENTO: 0.25,
            Outcome.ESFRIOU: 0.15,
        },
    ),
    "sensivel_preco": CustomerProfile(
        name="sensivel_preco",
        objections=("preco", "vou_pensar", "concorrente"),
        n_objections=(1, 2),
        asks_guarantee=0.3,
        split_messages=0.35,
        audio=0.15,
        lowercase_names=0.5,
        hard_negative=0.15,
        noise=(1, 3),
        outcome_weights={
            Outcome.GANHA: 0.3,
            Outcome.PERDIDA: 0.3,
            Outcome.EM_ANDAMENTO: 0.15,
            Outcome.ESFRIOU: 0.25,
        },
    ),
    "desconfiado": CustomerProfile(
        name="desconfiado",
        objections=("confianca", "cancelamento", "preco"),
        n_objections=(1, 3),
        asks_guarantee=0.7,
        split_messages=0.15,
        audio=0.1,
        lowercase_names=0.3,
        hard_negative=0.15,
        noise=(0, 2),
        outcome_weights={
            Outcome.GANHA: 0.25,
            Outcome.PERDIDA: 0.35,
            Outcome.EM_ANDAMENTO: 0.15,
            Outcome.ESFRIOU: 0.25,
        },
    ),
    "indeciso": CustomerProfile(
        name="indeciso",
        objections=("vou_pensar", "prazo", "preco", "confianca"),
        n_objections=(1, 3),
        asks_guarantee=0.4,
        split_messages=0.3,
        audio=0.2,
        lowercase_names=0.4,
        hard_negative=0.2,
        noise=(1, 2),
        outcome_weights={
            Outcome.GANHA: 0.2,
            Outcome.PERDIDA: 0.15,
            Outcome.EM_ANDAMENTO: 0.25,
            Outcome.ESFRIOU: 0.4,
        },
    ),
    "apressado": CustomerProfile(
        name="apressado",
        objections=("prazo", "preco", "vou_pensar"),
        n_objections=(0, 2),
        asks_guarantee=0.4,
        split_messages=0.6,
        audio=0.3,
        lowercase_names=0.7,
        hard_negative=0.2,
        noise=(2, 3),
        outcome_weights={
            Outcome.GANHA: 0.45,
            Outcome.PERDIDA: 0.25,
            Outcome.EM_ANDAMENTO: 0.1,
            Outcome.ESFRIOU: 0.2,
        },
    ),
}
