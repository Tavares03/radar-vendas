"""Gerador de conversas de venda: roteiro, texto, anotação e verdade de referência.

Cada conversa segue o funil (contato → qualificação → apresentação → proposta → negociação →
fechamento) com desvios sorteados pelos perfis de vendedor e cliente. Tudo que o gerador decide
vira anotação: rótulos por mensagem, dados pessoais com posição, objeções e como foram tratadas,
pedidos atendidos ou não e os alertas que o Radar deveria levantar.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import datetime, timedelta

from radar.taxonomy import DEFAULT_SEVERITY, RISK_TYPES, FunnelStage, Outcome
from radar_synth import __version__
from radar_synth.banks import Act, Bank, Template, load_bank
from radar_synth.fake import format_phone
from radar_synth.model import (
    ExpectedAlert,
    ObjectionRecord,
    PiiAnnotation,
    RequestRecord,
    SynthConversation,
    SynthMessage,
)
from radar_synth.profiles import CUSTOMER_PROFILES, SELLER_PROFILES, CustomerProfile, SellerProfile
from radar_synth.render import MessageStyle, Renderer, SlotContext

FamilyFilter = Callable[[str], bool]

#: Resposta ruim de um vendedor a cada objeção (vira o risco correspondente) e as famílias que
#: combinam com o assunto, quando o setor as tem.
BAD_RESPONSE: dict[str, tuple[str, tuple[str, ...]]] = {
    "preco": ("vendedor.pressao_abusiva", ("so_hoje", "insistencia")),
    "confianca": ("vendedor.promessa_indevida", ("garantido", "aprova", "resultado", "defeito")),
    "prazo": ("vendedor.promessa_indevida", ("quando_contempla", "aprova", "entrega", "aprovacao")),
    "vou_pensar": ("vendedor.pressao_abusiva", ("insistencia", "ameaca", "so_hoje")),
    "concorrente": ("vendedor.linguagem_inadequada", ("desdem",)),
    "cancelamento": ("vendedor.informacao_enganosa", ("cancelamento",)),
}

#: Que dado o cliente manda quando o vendedor pede (peso relativo; o setor ajusta alguns).
DATA_ACTS: dict[str, float] = {
    "cliente.envia_cpf": 3.0,
    "cliente.envia_email": 3.0,
    "cliente.envia_telefone": 2.0,
    "cliente.envia_endereco": 2.0,
    "cliente.envia_rg": 1.5,
    "cliente.envia_cnpj": 0.7,
    "cliente.envia_dados_completos": 2.0,
}

#: Pergunta → resposta: a resposta prefere a família com a mesma chave da pergunta.
_PAIRED = {
    "vendedor.qualificacao": "cliente.responde_qualificacao",
    "cliente.pergunta_info": "vendedor.responde_info",
    "cliente.pergunta_garantia": "vendedor.negativa_correta",
}

#: Demora (em minutos, dentro do horário comercial) a partir da qual o gerador anota
#: ``demora_resposta``. O SLA de cada empresa é configurável; este é o limite da referência.
SLOW_REPLY_MINUTES = 60
#: Silêncio do cliente (em horas) a partir do qual faltou follow-up do vendedor.
FOLLOW_UP_HOURS = 48
#: Mensagem do vendedor que conta como follow-up: enviada pelo menos este tempo depois do cliente.
FOLLOW_UP_GAP = timedelta(hours=20)
INJECTION_RATE = 0.04


def _weighted[T](rng: random.Random, options: dict[T, float]) -> T:
    keys = list(options)
    return rng.choices(keys, weights=[options[k] for k in keys])[0]


#: Horário comercial de referência (o padrão das empresas no Radar): seg–sex, 8h às 18h.
BUSINESS_START, BUSINESS_END = 8, 18


def business_minutes(start: datetime, end: datetime) -> int:
    """Minutos entre ``start`` e ``end`` que caem no horário comercial."""
    total = 0.0
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end:
        if day.weekday() < 5:
            opens = day.replace(hour=BUSINESS_START)
            closes = day.replace(hour=BUSINESS_END)
            overlap = (min(end, closes) - max(start, opens)).total_seconds()
            total += max(0.0, overlap)
        day += timedelta(days=1)
    return int(total // 60)


class _Script:
    def __init__(
        self,
        *,
        rng: random.Random,
        bank: Bank,
        seller: SellerProfile,
        customer: CustomerProfile,
        allow_family: FamilyFilter,
        start: datetime,
    ) -> None:
        self.rng = rng
        self.bank = bank
        self.seller = seller
        self.customer = customer
        self.allow_family = allow_family
        self.context = SlotContext.create(rng, bank)
        self.renderer = Renderer(bank, rng, self.context)
        self.clock = start
        self.stage = FunnelStage.PRIMEIRO_CONTATO
        self.messages: list[SynthMessage] = []
        self.requests: list[RequestRecord] = []
        self.objections: list[ObjectionRecord] = []
        self.signals: list[tuple[int, bool]] = []
        self.injection: int | None = None
        self.slow_reply: int | None = None
        self.used: dict[str, set[str]] = {}
        self.seller_display, self.customer_display = self._display_names()

    # ------------------------------------------------------------ nomes no export
    def _display_names(self) -> tuple[str, str]:
        seller = self.context.seller
        company = self.context.vocab_value("empresa", self.rng)
        seller_display = self.rng.choice(
            (seller.name, f"{seller.first_name} - {company}", f"{seller.first_name} {company}")
        )
        customer = self.context.customer
        roll = self.rng.random()
        if roll < 0.55:
            customer_display = customer.name
        elif roll < 0.8:
            customer_display = format_phone(*customer.phone, "intl")
        else:
            customer_display = customer.first_name
        if customer_display == seller_display:
            customer_display = customer.name + " " + customer.name.split()[-1][0] + "."
        return seller_display, customer_display

    # ------------------------------------------------------------ tempo
    def _advance(self, role: str) -> None:
        previous = self.messages[-1] if self.messages else None
        if previous is None:
            return
        if previous.sender == role:
            self.clock += timedelta(seconds=self.rng.randint(8, 150))
            return
        if role == "vendedor":
            low, high = self.seller.reply_minutes
            minutes = self.rng.uniform(low, high)
            if self.rng.random() < self.seller.slow_reply:
                minutes = self.rng.uniform(90, 600)
            moment = self.clock + timedelta(minutes=minutes)
            if not (moment.weekday() < 6 and 8 <= moment.hour < 19):
                moment = self._next_morning(moment)
            if self.slow_reply is None:
                waited = business_minutes(previous.timestamp, moment)
                if waited > SLOW_REPLY_MINUTES:
                    self.slow_reply = len(self.messages)
            self.clock = moment
        else:
            minutes = self.rng.choice(
                (self.rng.uniform(0.5, 10), self.rng.uniform(10, 120), self.rng.uniform(120, 900))
            )
            self.clock += timedelta(minutes=minutes)
            if self.clock.hour < 7:
                self.clock = self.clock.replace(hour=self.rng.randint(7, 9))

    def _next_morning(self, moment: datetime) -> datetime:
        day = moment if moment.hour < 8 else moment + timedelta(days=1)
        while day.weekday() == 6:
            day += timedelta(days=1)
        return day.replace(hour=8, minute=self.rng.randint(0, 59), second=self.rng.randint(0, 59))

    def wait_days(self, low: float, high: float) -> None:
        self.clock += timedelta(hours=self.rng.uniform(low * 24, high * 24))
        self.clock = self._next_morning(self.clock) if self.clock.hour >= 19 else self.clock

    # ------------------------------------------------------------ fala
    def _pick(self, act: Act, prefer: tuple[str, ...]) -> Template:
        families = [f for f in act.families if self.allow_family(f)]
        if not families:
            raise ValueError(f"nenhuma família permitida para o ato {act.name}")
        used = self.used.setdefault(act.name, set())
        fresh = [f for f in families if f not in used] or families
        preferred = [f for f in fresh if f.rsplit(".", 1)[1] in prefer]
        family = self.rng.choice(preferred or fresh)
        used.add(family)
        return self.rng.choice([t for t in act.templates if t.family == family])

    def _paired_key(self, act_name: str) -> tuple[str, ...]:
        if not self.messages:
            return ()
        previous = self.messages[-1]
        if _PAIRED.get(previous.act) == act_name:
            return (previous.family.rsplit(".", 1)[1],)
        return ()

    def _style(self, role: str, template: Template) -> MessageStyle:
        if role == "cliente":
            low, high = self.customer.noise
            audio = self.rng.random() < self.customer.audio and len(template.text) > 25
            return MessageStyle(
                noise=self.rng.randint(low, high),
                split=self.rng.random() < self.customer.split_messages,
                lowercase_names=self.rng.random() < self.customer.lowercase_names,
                emoji=self.rng.random() < 0.3,
                audio=audio,
                lowercase=self.rng.random() < 0.3 * high,
            )
        low, high = self.seller.noise
        return MessageStyle(
            noise=self.rng.randint(low, high),
            split=self.rng.random() < 0.15,
            emoji=self.rng.random() < 0.25,
            audio=self.rng.random() < 0.04 and len(template.text) > 25,
        )

    def say(self, act_name: str, prefer: tuple[str, ...] = ()) -> int:
        """Escreve um ato (uma ou mais mensagens). Devolve o índice da última mensagem."""
        act = self.bank.acts[act_name]
        role = act.role.value
        template = self._pick(act, prefer or self._paired_key(act_name))
        style = self._style(role, template)
        parts = self.renderer.render(template.text, style)
        for position, part in enumerate(parts):
            self._advance(role)
            self.clock = self.clock.replace(microsecond=0)  # o WhatsApp registra até o segundo
            last = position == len(parts) - 1
            self.messages.append(
                SynthMessage(
                    index=len(self.messages),
                    sender=role,
                    author=self.seller_display if role == "vendedor" else self.customer_display,
                    timestamp=self.clock,
                    kind="audio" if style.audio else "texto",
                    text=part.text,
                    labels=list(act.labels) if last else [],
                    pii=[PiiAnnotation(s.type.value, s.start, s.end, s.value) for s in part.spans],
                    act=act_name,
                    family=template.family,
                    stage=self.stage.value,
                )
            )
        return len(self.messages) - 1

    def maybe(self, probability: float, act_name: str) -> int | None:
        return self.say(act_name) if self.rng.random() < probability else None

    # ------------------------------------------------------------ cenas
    def opening(self) -> None:
        if self.rng.random() < 0.75:
            self.say("cliente.abertura")
            self.say("vendedor.saudacao")
            if self.rng.random() < 0.7:
                self.say("vendedor.qualificacao")
        else:
            self.say("vendedor.saudacao")
            self.say(self.rng.choice(("cliente.ack", "cliente.abertura")))
            self.say("vendedor.qualificacao")

    def qualification(self) -> None:
        self.stage = FunnelStage.QUALIFICACAO
        if self.messages[-1].act != "vendedor.qualificacao":
            self.say("vendedor.qualificacao")
        self.say("cliente.responde_qualificacao")
        if self.rng.random() < 0.4:
            self.say("vendedor.qualificacao")
            self.say("cliente.responde_qualificacao")

    def presentation(self) -> None:
        self.stage = FunnelStage.APRESENTACAO
        self.say("vendedor.apresentacao")
        roll = self.rng.random()
        if roll < self.seller.misleading:
            self.say("vendedor.informacao_enganosa")
        elif roll < self.seller.misleading + self.seller.disclose:
            self.say("vendedor.divulgacao")
        self.maybe(0.3, "cliente.ack")
        if self.rng.random() < 0.5:
            self.say("cliente.pergunta_info")
            self.maybe(0.6 + 0.4 * self.seller.answer_request, "vendedor.responde_info")
        if self.rng.random() < self.customer.asks_guarantee:
            question = self.say("cliente.pergunta_garantia")
            if self.rng.random() < self.seller.promise_on_guarantee:
                key = self.messages[question].family.rsplit(".", 1)[1]
                self.say("vendedor.promessa_indevida", (key,))
            else:
                self.say("vendedor.negativa_correta")

    def request(self) -> None:
        if self.rng.random() >= 0.85:
            return
        self.stage = FunnelStage.PROPOSTA
        document = self.rng.random() < 0.25
        index = self.say("cliente.pede_documento" if document else "cliente.pede_simulacao")
        record = RequestRecord(message_index=index, chain=len(self.requests))
        self.requests.append(record)
        if self.rng.random() < self.seller.answer_request:
            self.maybe(0.3, "vendedor.ack")
            record.answered_by = self.say(
                "vendedor.envia_documento" if document else "vendedor.envia_simulacao"
            )
            return
        if self.rng.random() < 0.5:
            self.maybe(0.5, "vendedor.qualificacao")
            follow = self.say("cliente.cobra_retorno")
            chained = RequestRecord(message_index=follow, chain=record.chain)
            self.requests.append(chained)
            if self.rng.random() < self.seller.answer_request:
                answer = self.say(
                    "vendedor.envia_documento" if document else "vendedor.envia_simulacao"
                )
                record.answered_by = chained.answered_by = answer

    def negotiation(self) -> None:
        low, high = self.customer.n_objections
        count = min(self.rng.randint(low, high), len(self.customer.objections))
        if count:
            self.stage = FunnelStage.NEGOCIACAO
        for objection in self.rng.sample(self.customer.objections, count):
            if self.rng.random() < self.customer.hard_negative * 0.5:
                self.say("cliente.negacao_dificil")
                self.maybe(0.5, "vendedor.ack")
            index = self.say(f"cliente.objecao_{objection}")
            handling = _weighted(
                self.rng,
                dict(
                    zip(
                        ("bem", "parcial", "mal", "sem_resposta"), self.seller.handling, strict=True
                    )
                ),
            )
            record = ObjectionRecord(
                type=f"objecao_{objection}", message_index=index, handling=handling
            )
            if handling in ("bem", "parcial"):
                record.answered_by = self.say(f"vendedor.resposta_{objection}.{handling}")
            elif handling == "mal":
                act_name, prefer = BAD_RESPONSE[objection]
                record.answered_by = self.say(act_name, prefer)
            self.objections.append(record)
        if self.rng.random() < self.customer.hard_negative * 0.5:
            self.say("cliente.negacao_dificil")

    def _data_acts(self) -> dict[str, float]:
        weights = dict(DATA_ACTS)
        weights["cliente.envia_placa"] = 3.0 if self.bank.sector == "seguros" else 0.4
        if self.bank.sector in ("generico", "imobiliaria"):
            weights["cliente.envia_cnpj"] = 2.0
        return weights

    def personal_data(self, outcome: str) -> None:
        if outcome == Outcome.PERDIDA and self.rng.random() < 0.7:
            return
        if self.rng.random() < self.seller.improper_data:
            self.say("vendedor.dados_pessoais_indevidos")
            if self.rng.random() < 0.45:
                self.say("cliente.envia_cartao")
            else:
                self.say("cliente.ack")
            return
        self.say("vendedor.pede_dados")
        weights = self._data_acts()
        first = _weighted(self.rng, weights)
        self.say(first)
        if self.rng.random() < 0.35:
            weights.pop(first)
            self.say(_weighted(self.rng, weights))
        self.maybe(0.4, "vendedor.ack")

    def refund_details(self, outcome: str) -> None:
        """Cliente manda chave PIX ou conta (reembolso, devolução): dado bancário do cliente."""
        chance = 0.25 if outcome == Outcome.PERDIDA else 0.05
        if self.rng.random() < chance:
            self.say("cliente.envia_pix")
            self.maybe(0.6, "vendedor.ack")

    def signal(self, *, thank: bool) -> bool:
        self.stage = FunnelStage.FECHAMENTO
        index = self.say("cliente.sinal_compra")
        roll = self.rng.random()
        handled = True
        if roll < self.seller.off_channel:
            self.say("vendedor.pagamento_fora_canal")
        elif roll < self.seller.off_channel + self.seller.close_on_signal:
            self.say("vendedor.fechamento")
        else:
            handled = False
        self.signals.append((index, handled))
        if handled and thank:
            self.stage = FunnelStage.POS_VENDA
            self.say("cliente.agradece")
            self.maybe(0.8, "vendedor.despedida")
        return handled

    def closing(self, outcome: str) -> None:
        if outcome == Outcome.GANHA:
            self.signal(thank=True)
        elif outcome == Outcome.PERDIDA:
            self.say("cliente.desiste")
            if self.rng.random() < self.seller.rude_on_loss:
                self.say("vendedor.linguagem_inadequada")
            else:
                self.maybe(0.8, "vendedor.despedida")
        elif outcome == Outcome.EM_ANDAMENTO:
            if self.rng.random() < 0.5:
                self.signal(thank=False)
            else:
                self.say("vendedor.despedida")
        else:  # esfriou: o cliente some
            if self.messages[-1].sender == "cliente":
                self.say("vendedor.ack")
            if self.rng.random() < self.seller.follow_up:
                self.wait_days(1, 3)
                self.say("vendedor.followup")
                if self.rng.random() < 0.3:
                    self.say("cliente.retorno_atrasado")
                    self.say("vendedor.ack")

    def injection_attempt(self) -> None:
        if self.rng.random() < INJECTION_RATE:
            self.injection = self.say("cliente.injecao")
            self.maybe(0.5, "vendedor.ack")

    # ------------------------------------------------------------ referência
    def expected_alerts(self, outcome: str, exported_at: datetime) -> list[ExpectedAlert]:
        alerts: list[ExpectedAlert] = []

        def add(kind: str, index: int | None, note: str = "") -> None:
            alerts.append(ExpectedAlert(kind, DEFAULT_SEVERITY[kind].value, index, note))

        for message in self.messages:
            for label in message.labels:
                if label in RISK_TYPES:
                    add(label, message.index)
        chains: dict[int, list[RequestRecord]] = {}
        for request in self.requests:
            chains.setdefault(request.chain, []).append(request)
        for records in chains.values():
            if records[0].answered_by is None:
                add("pedido_pendente", records[0].message_index, "pedido sem resposta")
        for objection in self.objections:
            if objection.handling == "sem_resposta":
                add("objecao_sem_resposta", objection.message_index, objection.type)
        for index, handled in self.signals:
            if not handled:
                add("sinal_compra_ignorado", index)
        if self.injection is not None:
            add("tentativa_manipulacao", self.injection)
        if self.slow_reply is not None:
            add("demora_resposta", self.slow_reply, f"mais de {SLOW_REPLY_MINUTES} min")
        # Mesma definição da métrica do Radar: o cliente parou de responder, o vendedor falou por
        # último e não retomou o contato (nenhuma mensagem 20 h ou mais depois do cliente).
        customer = [m for m in self.messages if m.sender == "cliente"]
        if customer:
            last = customer[-1]
            trailing = [m for m in self.messages[last.index + 1 :] if m.sender == "vendedor"]
            followed = any(m.timestamp - last.timestamp >= FOLLOW_UP_GAP for m in trailing)
            closed = last.act in ("cliente.agradece", "cliente.desiste")
            silence = (exported_at - last.timestamp).total_seconds() / 3600
            if trailing and not followed and not closed and silence >= FOLLOW_UP_HOURS:
                add("follow_up_ausente", None, f"cliente em silêncio há {int(silence)} h")
                if self.requests or self.signals:
                    add("lead_esfriando", None, "cliente demonstrou interesse e sumiu")
        return alerts


def _start_time(rng: random.Random) -> datetime:
    day = datetime(2024, 1, 2) + timedelta(days=rng.randrange(0, 640))
    while day.weekday() == 6:
        day += timedelta(days=1)
    return day.replace(
        hour=rng.randint(8, 20), minute=rng.randint(0, 59), second=rng.randint(0, 59)
    )


def generate_conversation(
    *,
    seed: int,
    sector: str,
    seller_profile: str | None = None,
    customer_profile: str | None = None,
    allow_family: FamilyFilter | None = None,
    split: str = "train",
    conversation_id: str | None = None,
) -> SynthConversation:
    """Gera uma conversa completa. A mesma ``seed`` (e os mesmos bancos) geram a mesma conversa."""
    rng = random.Random(f"{sector}:{seed}")
    bank = load_bank(sector)
    seller = SELLER_PROFILES[seller_profile or rng.choice(sorted(SELLER_PROFILES))]
    customer = CUSTOMER_PROFILES[customer_profile or rng.choice(sorted(CUSTOMER_PROFILES))]

    weights = dict(customer.outcome_weights)
    if seller.name == "bom":
        weights[Outcome.GANHA] *= 1.5
    elif seller.name == "problematico":
        weights[Outcome.GANHA] *= 0.6
        weights[Outcome.PERDIDA] *= 1.4
    outcome = str(_weighted(rng, weights))

    script = _Script(
        rng=rng,
        bank=bank,
        seller=seller,
        customer=customer,
        allow_family=allow_family or (lambda _family: True),
        start=_start_time(rng),
    )
    script.opening()
    script.injection_attempt()
    script.qualification()
    script.presentation()
    script.request()
    script.negotiation()
    script.personal_data(outcome)
    script.refund_details(outcome)
    script.closing(outcome)

    # Conversa que esfriou é exportada dias depois; as demais, antes do prazo de follow-up.
    hours = (
        rng.uniform(FOLLOW_UP_HOURS + 2, 240)
        if outcome == Outcome.ESFRIOU
        else rng.uniform(1, FOLLOW_UP_HOURS - 10)
    )
    exported_at = script.clock + timedelta(hours=hours)
    return SynthConversation(
        id=conversation_id or f"{sector}-{seed:06d}",
        seed=seed,
        sector=sector,
        split=split,
        seller_profile=seller.name,
        customer_profile=customer.name,
        outcome=outcome,
        company=script.context.vocab_value("empresa", rng),
        seller_display=script.seller_display,
        customer_display=script.customer_display,
        messages=script.messages,
        exported_at=exported_at.replace(microsecond=0),
        expected_alerts=script.expected_alerts(outcome, exported_at),
        requests=script.requests,
        objections=script.objections,
        generator_version=__version__,
    )
