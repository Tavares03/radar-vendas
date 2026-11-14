"""Dados pessoais 100% falsos, no formato brasileiro.

CPFs, CNPJs, cartões e telefones passam nos validadores (dígitos verificadores, Luhn, DDD), mas
são sorteados: não pertencem a ninguém de propósito. E-mails usam domínios fictícios. Tudo vem de
um ``random.Random`` recebido de fora, então a mesma semente gera os mesmos dados.
"""

from __future__ import annotations

import random
import unicodedata
import uuid

from radar.privacy.validators import VALID_DDDS, is_valid_cpf, words

FIRST_NAMES_F = words(
    """
    Ana Maria Juliana Fernanda Patrícia Aline Camila Amanda Bruna Jéssica Letícia Mariana Vanessa
    Gabriela Larissa Beatriz Carla Daniela Renata Débora Luana Bianca Tatiane Priscila Natália
    Raquel Simone Viviane Cristiane Sandra Lúcia Helena Rosana Fabiana Eduarda Isabela Laura
    Sofia Valentina Lorena Yasmin Thaís Elaine Kelly Rita Sueli Márcia Cláudia Adriana Joana
    """
)
FIRST_NAMES_M = words(
    """
    João José Antônio Francisco Carlos Paulo Pedro Lucas Luiz Marcos Luís Gabriel Rafael Daniel
    Marcelo Bruno Eduardo Felipe Raimundo Rodrigo Manoel Mateus André Fernando Fábio Leonardo
    Gustavo Guilherme Leandro Tiago Anderson Ricardo Márcio Jorge Sebastião Alexandre Roberto
    Edson Diego Vitor Sérgio Cláudio Renato Igor Otávio Henrique Caio Murilo Wesley Douglas
    """
)
SURNAMES = words(
    """
    Silva Santos Oliveira Souza Rodrigues Ferreira Alves Pereira Lima Gomes Costa Ribeiro Martins
    Carvalho Almeida Lopes Soares Fernandes Vieira Barbosa Rocha Dias Nascimento Andrade Moreira
    Nunes Marques Machado Mendes Freitas Cardoso Ramos Gonçalves Santana Teixeira Araújo Pinto
    Moura Cavalcanti Monteiro Batista Campos Correia Rezende Farias Brito Azevedo Bezerra Castro
    """
)
_STREET_TYPES = ("Rua", "Rua", "Rua", "Avenida", "Av.", "Travessa", "Alameda", "Estrada")
_STREET_NAMES = (
    "das Flores",
    "das Acácias",
    "Sete de Setembro",
    "Quinze de Novembro",
    "Brasil",
    "Santos Dumont",
    "Dom Pedro II",
    "Tiradentes",
    "das Palmeiras",
    "Boa Vista",
    "São João",
    "XV de Agosto",
    "dos Andradas",
    "Rio Branco",
    "Getúlio Vargas",
    "Marechal Deodoro",
    "das Laranjeiras",
    "Bela Vista",
    "do Comércio",
    "Ipiranga",
)
_COMPLEMENTS = ("apto 12", "apto 304", "casa 2", "bloco B", "fundos", "sala 5", "ap 41")
_EMAIL_DOMAINS = (
    "exemplo.com",
    "exemplo.com.br",
    "email.exemplo.com",
    "teste.com.br",
    "correio.example",
    "mail.test",
)
_PLATE_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_DDDS = tuple(sorted(VALID_DDDS))
_CNPJ_WEIGHTS_1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_CNPJ_WEIGHTS_2 = (6, *_CNPJ_WEIGHTS_1)


def _ascii(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


PHONE_STYLES = ("paren", "paren", "space", "intl", "digits")


def format_phone(ddd: str, number: str, style: str) -> str:
    head, tail = number[:-4], number[-4:]
    if style == "paren":
        return f"({ddd}) {head}-{tail}"
    if style == "space":
        return f"{ddd} {head}-{tail}"
    if style == "intl":
        return f"+55 {ddd} {head}-{tail}"
    return ddd + number


def format_cpf(digits: str, *, formatted: bool) -> str:
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}" if formatted else digits


def _cnpj_check(values: list[int], weights: tuple[int, ...]) -> int:
    remainder = sum(v * w for v, w in zip(values, weights, strict=True)) % 11
    return 0 if remainder < 2 else 11 - remainder


class FakeData:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    # ------------------------------------------------------------ pessoas
    def first_name(self, gender: str | None = None) -> str:
        gender = gender or self.rng.choice("FM")
        pool = FIRST_NAMES_F if gender == "F" else FIRST_NAMES_M
        return self.rng.choice(sorted(pool))

    def surname(self) -> str:
        return self.rng.choice(sorted(SURNAMES))

    def full_name(self, gender: str | None = None) -> str:
        parts = [self.first_name(gender), self.surname()]
        if self.rng.random() < 0.3:
            parts.insert(1, self.surname() if self.rng.random() < 0.5 else "de " + self.surname())
        return " ".join(parts)

    # ------------------------------------------------------------ documentos
    def cpf(self, *, formatted: bool = True) -> str:
        while True:
            digits = [self.rng.randrange(10) for _ in range(9)]
            if len(set(digits)) > 1:
                break
        for size in (9, 10):
            total = sum(d * (size + 1 - i) for i, d in enumerate(digits[:size]))
            digits.append((total * 10) % 11 % 10)
        return format_cpf("".join(map(str, digits)), formatted=formatted)

    def cnpj(self, *, formatted: bool = True, alphanumeric: bool = False) -> str:
        if alphanumeric:
            head = [self.rng.choice(_ALNUM) for _ in range(8)]
            head[self.rng.randrange(8)] = self.rng.choice(_ALNUM[:26])  # pelo menos uma letra
            branch = [self.rng.choice(_ALNUM) for _ in range(4)]
            chars = head + branch
        else:
            chars = [str(self.rng.randrange(10)) for _ in range(8)] + list("0001")
        values = [ord(ch) - 48 for ch in chars]
        first = _cnpj_check(values, _CNPJ_WEIGHTS_1)
        second = _cnpj_check([*values, first], _CNPJ_WEIGHTS_2)
        raw = "".join(chars) + f"{first}{second}"
        if not formatted:
            return raw
        return f"{raw[:2]}.{raw[2:5]}.{raw[5:8]}/{raw[8:12]}-{raw[12:]}"

    def rg(self) -> str:
        digits = "".join(str(self.rng.randrange(10)) for _ in range(8))
        check = self.rng.choice("0123456789X")
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:]}-{check}"

    # ------------------------------------------------------------ contato
    def phone_parts(self, *, mobile: bool | None = None) -> tuple[str, str]:
        """``(DDD, número)`` de um telefone válido que não é, por acaso, também um CPF válido."""
        mobile = self.rng.random() < 0.85 if mobile is None else mobile
        while True:
            ddd = self.rng.choice(_DDDS)
            if mobile:
                number = "9" + "".join(str(self.rng.randrange(10)) for _ in range(8))
            else:
                number = str(self.rng.randrange(2, 6)) + "".join(
                    str(self.rng.randrange(10)) for _ in range(7)
                )
            if not is_valid_cpf(ddd + number):
                return ddd, number

    def phone_style(self) -> str:
        return self.rng.choice(PHONE_STYLES)

    def phone(self, style: str | None = None, *, mobile: bool | None = None) -> str:
        ddd, number = self.phone_parts(mobile=mobile)
        return format_phone(ddd, number, style or self.phone_style())

    def email(self, name: str) -> str:
        parts = _ascii(name).lower().replace("de ", "").split()
        first, last = parts[0], parts[-1]
        user = self.rng.choice(
            (
                f"{first}.{last}",
                f"{first}{last}",
                f"{first}_{last}",
                f"{first}{self.rng.randrange(70, 100)}",
                f"{first[0]}{last}",
            )
        )
        return f"{user}@{self.rng.choice(_EMAIL_DOMAINS)}"

    # ------------------------------------------------------------ endereço
    def cep(self, *, formatted: bool = True) -> str:
        while True:
            digits = "".join(str(self.rng.randrange(10)) for _ in range(8))
            if len(set(digits)) > 1:
                break
        return f"{digits[:5]}-{digits[5:]}" if formatted else digits

    def address(self) -> str:
        street = f"{self.rng.choice(_STREET_TYPES)} {self.rng.choice(_STREET_NAMES)}"
        number = str(self.rng.randrange(10, 3000))
        separator = self.rng.choice((", ", ", nº ", " "))
        text = f"{street}{separator}{number}"
        if self.rng.random() < 0.35:
            text += f", {self.rng.choice(_COMPLEMENTS)}"
        return text

    # ------------------------------------------------------------ financeiro
    def pix_random_key(self) -> str:
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))

    def bank_account(self) -> tuple[str, str]:
        agency = f"{self.rng.randrange(1, 10000):04d}"
        size = self.rng.randrange(4, 9)
        account = "".join(str(self.rng.randrange(10)) for _ in range(size))
        return agency, f"{account}-{self.rng.randrange(10)}"

    def card_number(self, *, grouped: bool = True) -> str:
        digits = [self.rng.choice((4, 5))] + [self.rng.randrange(10) for _ in range(14)]
        total = 0
        for index, digit in enumerate(reversed(digits)):
            value = digit * 2 if index % 2 == 0 else digit
            total += value - 9 if value > 9 else value
        digits.append((10 - total % 10) % 10)
        raw = "".join(map(str, digits))
        return " ".join(raw[i : i + 4] for i in range(0, 16, 4)) if grouped else raw

    # ------------------------------------------------------------ veículo
    def plate(self) -> str:
        letters = "".join(self.rng.choice(_PLATE_LETTERS) for _ in range(3))
        if self.rng.random() < 0.5:
            return f"{letters}-{self.rng.randrange(10000):04d}"
        return (
            f"{letters}{self.rng.randrange(10)}{self.rng.choice('ABCDEFGHIJ')}"
            f"{self.rng.randrange(100):02d}"
        )
