"""Vocabulário único do Radar de Vendas.

Regras, classificador, dataset sintético, API e painel falam a mesma língua: estes enums são a
fonte da verdade. A ordem de :data:`CLASSIFIER_LABELS` e de :data:`PII_TYPES` é contrato com os
modelos treinados; mudar a ordem exige retreinar.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Papel de um usuário dentro da empresa."""

    ADMIN = "admin"
    GESTOR = "gestor"
    VENDEDOR = "vendedor"
    AUDITOR = "auditor"


class SenderRole(StrEnum):
    """Quem escreveu a mensagem."""

    VENDEDOR = "vendedor"
    CLIENTE = "cliente"
    SISTEMA = "sistema"
    OUTRO = "outro"


class Severity(StrEnum):
    INFO = "info"
    ATENCAO = "atencao"
    CRITICO = "critico"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.ATENCAO: 1,
    Severity.CRITICO: 2,
}


class AlertCategory(StrEnum):
    RISCO = "risco"
    OPORTUNIDADE = "oportunidade"
    QUALIDADE = "qualidade"


class RiskType(StrEnum):
    """Riscos de compliance em mensagens do vendedor."""

    PROMESSA_INDEVIDA = "promessa_indevida"
    INFORMACAO_ENGANOSA = "informacao_enganosa"
    PRESSAO_ABUSIVA = "pressao_abusiva"
    PAGAMENTO_FORA_CANAL = "pagamento_fora_canal"
    LINGUAGEM_INADEQUADA = "linguagem_inadequada"
    DADOS_PESSOAIS_INDEVIDOS = "dados_pessoais_indevidos"


class ObjectionType(StrEnum):
    """Objeções em mensagens do cliente."""

    PRECO = "objecao_preco"
    CONFIANCA = "objecao_confianca"
    PRAZO = "objecao_prazo"
    VOU_PENSAR = "objecao_vou_pensar"
    CONCORRENTE = "objecao_concorrente"
    CANCELAMENTO = "objecao_cancelamento"


class IntentType(StrEnum):
    """Intenção em mensagens do cliente."""

    SINAL_COMPRA = "sinal_compra"
    PEDIDO_CLIENTE = "pedido_cliente"


class OpportunityType(StrEnum):
    """Alertas de oportunidade e qualidade, derivados da conversa inteira."""

    PEDIDO_PENDENTE = "pedido_pendente"
    OBJECAO_SEM_RESPOSTA = "objecao_sem_resposta"
    SINAL_COMPRA_IGNORADO = "sinal_compra_ignorado"
    DEMORA_RESPOSTA = "demora_resposta"
    FOLLOW_UP_AUSENTE = "follow_up_ausente"
    LEAD_ESFRIANDO = "lead_esfriando"


class SecurityAlertType(StrEnum):
    """Alertas sobre a própria análise (não sobre o vendedor)."""

    TENTATIVA_MANIPULACAO = "tentativa_manipulacao"


class PiiType(StrEnum):
    """Tipos de dado pessoal detectados e mascarados."""

    CPF = "CPF"
    CNPJ = "CNPJ"
    RG = "RG"
    TELEFONE = "TELEFONE"
    EMAIL = "EMAIL"
    ENDERECO = "ENDERECO"
    CEP = "CEP"
    PIX = "PIX"
    CONTA_BANCARIA = "CONTA_BANCARIA"
    PLACA = "PLACA"
    NOME_PESSOA = "NOME_PESSOA"


class FunnelStage(StrEnum):
    PRIMEIRO_CONTATO = "primeiro_contato"
    QUALIFICACAO = "qualificacao"
    APRESENTACAO = "apresentacao"
    PROPOSTA = "proposta"
    NEGOCIACAO = "negociacao"
    FECHAMENTO = "fechamento"
    POS_VENDA = "pos_venda"


class Outcome(StrEnum):
    GANHA = "ganha"
    PERDIDA = "perdida"
    EM_ANDAMENTO = "em_andamento"
    ESFRIOU = "esfriou"


class Sentiment(StrEnum):
    POSITIVO = "positivo"
    NEUTRO = "neutro"
    NEGATIVO = "negativo"


class ObjectionHandling(StrEnum):
    """Como o vendedor tratou uma objeção."""

    BEM = "bem"
    PARCIAL = "parcial"
    MAL = "mal"
    SEM_RESPOSTA = "sem_resposta"


class AlertStatus(StrEnum):
    ABERTO = "aberto"
    EM_REVISAO = "em_revisao"
    CONFIRMADO = "confirmado"
    RESOLVIDO = "resolvido"
    FALSO_POSITIVO = "falso_positivo"


class MessageKind(StrEnum):
    TEXTO = "texto"
    AUDIO = "audio"
    IMAGEM = "imagem"
    VIDEO = "video"
    DOCUMENTO = "documento"
    FIGURINHA = "figurinha"
    CONTATO = "contato"
    LOCALIZACAO = "localizacao"
    SISTEMA = "sistema"
    APAGADA = "apagada"
    OUTRO = "outro"


class ImportSource(StrEnum):
    """Por onde a conversa entrou."""

    WHATSAPP_EXPORT = "whatsapp_export"
    API = "api"
    WHATSAPP_CLOUD = "whatsapp_cloud"
    EVOLUTION = "evolution"
    DEMO = "demo"


class ImportStatus(StrEnum):
    PENDENTE = "pendente"
    PROCESSANDO = "processando"
    CONCLUIDO = "concluido"
    FALHOU = "falhou"


class ConversationStatus(StrEnum):
    PENDENTE = "pendente"
    PROCESSANDO = "processando"
    ANALISADA = "analisada"
    ERRO = "erro"


class TranscriptionStatus(StrEnum):
    NAO_APLICAVEL = "nao_aplicavel"
    PENDENTE = "pendente"
    CONCLUIDA = "concluida"
    FALHOU = "falhou"
    #: Áudio sem arquivo (export "sem mídia"), longo demais ou transcrição desligada.
    IGNORADA = "ignorada"


class AnalysisLayer(StrEnum):
    """Camada que produziu (ou avaliou) um achado."""

    REGRA = "regra"
    CLASSIFICADOR = "classificador"
    LLM = "llm"
    METRICA = "metrica"


RISK_TYPES: tuple[str, ...] = tuple(t.value for t in RiskType)
OBJECTION_TYPES: tuple[str, ...] = tuple(t.value for t in ObjectionType)
INTENT_TYPES: tuple[str, ...] = tuple(t.value for t in IntentType)
OPPORTUNITY_TYPES: tuple[str, ...] = tuple(t.value for t in OpportunityType)
PII_TYPES: tuple[str, ...] = tuple(t.value for t in PiiType)

#: Rótulos do classificador de mensagens, na ordem das saídas do modelo.
CLASSIFIER_LABELS: tuple[str, ...] = RISK_TYPES + OBJECTION_TYPES + INTENT_TYPES

#: Rótulos que só fazem sentido em mensagens do vendedor / do cliente.
SELLER_LABELS: frozenset[str] = frozenset(RISK_TYPES)
CUSTOMER_LABELS: frozenset[str] = frozenset(OBJECTION_TYPES + INTENT_TYPES)

LABELS_PT: dict[str, str] = {
    # riscos
    "promessa_indevida": "Promessa indevida",
    "informacao_enganosa": "Informação enganosa ou omissão",
    "pressao_abusiva": "Pressão abusiva ou urgência falsa",
    "pagamento_fora_canal": "Pagamento fora do canal oficial",
    "linguagem_inadequada": "Linguagem ofensiva ou inadequada",
    "dados_pessoais_indevidos": "Coleta ou compartilhamento indevido de dados",
    # objeções
    "objecao_preco": "Objeção de preço",
    "objecao_confianca": "Objeção de confiança",
    "objecao_prazo": "Objeção de prazo",
    "objecao_vou_pensar": 'Objeção "vou pensar"',
    "objecao_concorrente": "Objeção de concorrente",
    "objecao_cancelamento": "Objeção de cancelamento",
    # intenção
    "sinal_compra": "Sinal de compra",
    "pedido_cliente": "Pedido do cliente",
    # oportunidade e qualidade
    "pedido_pendente": "Pedido sem resposta",
    "objecao_sem_resposta": "Objeção sem resposta",
    "sinal_compra_ignorado": "Sinal de compra ignorado",
    "demora_resposta": "Demora na resposta",
    "follow_up_ausente": "Follow-up ausente",
    "lead_esfriando": "Lead esfriando",
    # segurança da análise
    "tentativa_manipulacao": "Tentativa de manipular a análise",
}

SEVERITY_PT: dict[str, str] = {"info": "Info", "atencao": "Atenção", "critico": "Crítico"}


def category_of(alert_type: str) -> AlertCategory:
    """Categoria de um tipo de alerta (risco, oportunidade ou qualidade)."""
    if alert_type in RISK_TYPES or alert_type == SecurityAlertType.TENTATIVA_MANIPULACAO:
        return AlertCategory.RISCO
    if alert_type in (
        OpportunityType.DEMORA_RESPOSTA,
        OpportunityType.FOLLOW_UP_AUSENTE,
    ):
        return AlertCategory.QUALIDADE
    return AlertCategory.OPORTUNIDADE


def label_pt(value: str) -> str:
    """Nome legível de um rótulo; devolve o próprio valor se for desconhecido."""
    return LABELS_PT.get(value, value)
