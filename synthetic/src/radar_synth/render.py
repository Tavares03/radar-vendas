"""Transforma um template em texto de mensagem com as posições exatas dos dados pessoais."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from radar.taxonomy import PiiType
from radar_synth.banks import PII_SLOTS, Bank
from radar_synth.fake import FakeData, format_cpf, format_phone
from radar_synth.noise import FILLERS, apply_noise, drop_final_period, message_suffix

_SLOT_RE = re.compile(r"\{(\w+)\}")
_ARTICLE_RE = re.compile(r"(?<![\wÀ-ÿ])([oaOA]) $")
_NAME_SLOTS = {
    "nome_cliente": "customer",
    "primeiro_nome_cliente": "customer",
    "nome_vendedor": "seller",
    "primeiro_nome_vendedor": "seller",
    "nome_terceiro": "third",
}


@dataclass(slots=True)
class Persona:
    """Uma pessoa fictícia e todos os seus dados (fixos durante a conversa)."""

    name: str
    gender: str
    cpf_digits: str
    phone: tuple[str, str]
    email: str
    address: str
    cep: str
    rg: str
    plate: str
    card: str

    @property
    def first_name(self) -> str:
        return self.name.split()[0]

    @classmethod
    def build(cls, rng: random.Random, *, gender: str | None = None) -> Persona:
        fake = FakeData(rng)
        gender = gender or rng.choice("FM")
        name = fake.full_name(gender)
        return cls(
            name=name,
            gender=gender,
            cpf_digits=fake.cpf(formatted=False),
            phone=fake.phone_parts(mobile=True),
            email=fake.email(name),
            address=fake.address(),
            cep=fake.cep(),
            rg=fake.rg(),
            plate=fake.plate(),
            card=fake.card_number(),
        )


@dataclass(slots=True)
class SlotContext:
    customer: Persona
    seller: Persona
    third: Persona
    company_cnpj: str
    customer_cnpj: str
    seller_pix: str
    seller_agency: str
    seller_account: str
    customer_pix: str
    customer_agency: str
    customer_account: str
    vocab: dict[str, list[str]]
    sticky: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(cls, rng: random.Random, bank: Bank) -> SlotContext:
        fake = FakeData(rng)
        agency, account = fake.bank_account()
        customer_agency, customer_account = fake.bank_account()
        seller = Persona.build(rng)
        customer = Persona.build(rng)

        def pix_of(person: Persona) -> str:
            return rng.choice(
                (
                    fake.pix_random_key(),
                    person.email,
                    format_phone(*person.phone, "paren"),
                    format_cpf(person.cpf_digits, formatted=True),
                )
            )

        return cls(
            customer=customer,
            seller=seller,
            third=Persona.build(rng),
            company_cnpj=fake.cnpj(alphanumeric=rng.random() < 0.2),
            customer_cnpj=fake.cnpj(formatted=rng.random() < 0.8, alphanumeric=rng.random() < 0.2),
            seller_pix=pix_of(seller),
            seller_agency=agency,
            seller_account=account,
            customer_pix=pix_of(customer),
            customer_agency=customer_agency,
            customer_account=customer_account,
            vocab=bank.vocab,
        )

    def persona(self, who: str) -> Persona:
        return {"customer": self.customer, "seller": self.seller, "third": self.third}[who]

    def vocab_value(self, slot: str, rng: random.Random) -> str:
        if slot not in self.sticky:
            self.sticky[slot] = rng.choice(self.vocab[slot])
        return self.sticky[slot]

    def pii_value(self, slot: str, rng: random.Random) -> str:
        customer, third = self.customer, self.third
        values = {
            "nome_cliente": lambda: customer.name,
            "primeiro_nome_cliente": lambda: customer.first_name,
            "nome_vendedor": lambda: self.seller.name,
            "primeiro_nome_vendedor": lambda: self.seller.first_name,
            "nome_terceiro": lambda: third.name,
            "cpf": lambda: format_cpf(customer.cpf_digits, formatted=rng.random() < 0.7),
            "cpf_terceiro": lambda: format_cpf(third.cpf_digits, formatted=True),
            "cnpj": lambda: self.customer_cnpj,
            "cnpj_empresa": lambda: self.company_cnpj,
            "rg": lambda: customer.rg,
            "telefone": lambda: format_phone(*customer.phone, FakeData(rng).phone_style()),
            "telefone_terceiro": lambda: format_phone(*third.phone, "paren"),
            "telefone_vendedor": lambda: format_phone(*self.seller.phone, "space"),
            "email": lambda: customer.email,
            "email_vendedor": lambda: self.seller.email,
            "endereco": lambda: customer.address,
            "cep": lambda: customer.cep,
            "pix_vendedor": lambda: self.seller_pix,
            "pix_cliente": lambda: self.customer_pix,
            "agencia_cliente": lambda: self.customer_agency,
            "conta_cliente": lambda: self.customer_account,
            "agencia_vendedor": lambda: self.seller_agency,
            "conta_vendedor": lambda: self.seller_account,
            "cartao": lambda: customer.card,
            "placa": lambda: customer.plate,
        }
        return values[slot]()


@dataclass(frozen=True, slots=True)
class RenderedSpan:
    type: PiiType
    start: int
    end: int
    value: str
    slot: str


@dataclass(slots=True)
class RenderedPart:
    text: str
    spans: list[RenderedSpan]


@dataclass(frozen=True, slots=True)
class MessageStyle:
    #: 0 (texto limpo) a 3 (muito informal).
    noise: int = 0
    #: Partes separadas por ``||`` viram mensagens diferentes.
    split: bool = False
    #: Nomes escritos em minúsculas ("oi carla").
    lowercase_names: bool = False
    emoji: bool = False
    #: Transcrição de áudio: fala, sem emoji nem abreviação.
    audio: bool = False
    lowercase: bool = False


class Renderer:
    def __init__(self, bank: Bank, rng: random.Random, context: SlotContext) -> None:
        self.bank = bank
        self.rng = rng
        self.context = context

    def render(self, template: str, style: MessageStyle) -> list[RenderedPart]:
        pieces = [p.strip() for p in template.split("||") if p.strip()]
        if not style.split:
            pieces = [" ".join(pieces)]
        parts = [self._render_part(piece, style, first=i == 0) for i, piece in enumerate(pieces)]
        if style.emoji and not style.audio and parts:
            last = parts[-1]
            last.text += message_suffix(self.rng, max(style.noise, 1))
        return parts

    def _render_part(self, text: str, style: MessageStyle, *, first: bool) -> RenderedPart:
        noise = 0 if style.audio else style.noise
        segments: list[tuple[str, str | None]] = []  # (texto, slot de dado pessoal ou None)
        cursor = 0
        for match in _SLOT_RE.finditer(text):
            literal = text[cursor : match.start()]
            slot = match.group(1)
            if slot in PII_SLOTS:
                value = self.context.pii_value(slot, self.rng)
                if slot in _NAME_SLOTS:
                    literal = self._fix_article(literal, self.context.persona(_NAME_SLOTS[slot]))
                    if style.lowercase_names:
                        value = value.lower()
                segments.append((literal, None))
                segments.append((value, slot))
            else:
                segments.append((literal + self.context.vocab_value(slot, self.rng), None))
            cursor = match.end()
        segments.append((text[cursor:], None))

        merged: list[tuple[str, str | None]] = []
        for chunk, slot in segments:
            if slot is None and merged and merged[-1][1] is None:
                merged[-1] = (merged[-1][0] + chunk, None)
            else:
                merged.append((chunk, slot))

        out: list[str] = []
        spans: list[RenderedSpan] = []
        length = 0
        for index, (chunk, slot) in enumerate(merged):
            if slot is None:
                chunk = apply_noise(chunk, self.rng, level=noise, lowercase=style.lowercase)
                if index == len(merged) - 1:
                    chunk = drop_final_period(chunk, self.rng, noise)
            else:
                spans.append(
                    RenderedSpan(PII_SLOTS[slot], length, length + len(chunk), chunk, slot)
                )
            out.append(chunk)
            length += len(chunk)
        rendered = "".join(out)

        if style.audio and first:
            filler = self.rng.choice(FILLERS) if self.rng.random() < 0.6 else ""
            if filler:
                head = rendered[:1].lower() if not spans or spans[0].start > 0 else rendered[:1]
                rendered = filler + head + rendered[1:]
                spans = [
                    RenderedSpan(
                        s.type, s.start + len(filler), s.end + len(filler), s.value, s.slot
                    )
                    for s in spans
                ]
        return RenderedPart(rendered, spans)

    @staticmethod
    def _fix_article(literal: str, persona: Persona) -> str:
        match = _ARTICLE_RE.search(literal)
        if match is None:
            return literal
        wanted = "a" if persona.gender == "F" else "o"
        if match.group(1).isupper():
            wanted = wanted.upper()
        return literal[: match.start(1)] + wanted + " "
