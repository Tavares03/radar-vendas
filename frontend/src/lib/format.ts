/** Formatação em português para o painel. */

const SEVERITY: Record<string, string> = { critico: "Crítico", atencao: "Atenção", info: "Info" };
const STATUS: Record<string, string> = {
  aberto: "Aberto",
  em_revisao: "Em revisão",
  confirmado: "Confirmado",
  resolvido: "Resolvido",
  falso_positivo: "Falso positivo",
};
const ROLE: Record<string, string> = {
  admin: "Administração",
  gestor: "Gestão",
  vendedor: "Vendas",
  auditor: "Auditoria",
};
const STAGE: Record<string, string> = {
  primeiro_contato: "Primeiro contato",
  qualificacao: "Qualificação",
  apresentacao: "Apresentação",
  proposta: "Proposta",
  negociacao: "Negociação",
  fechamento: "Fechamento",
  pos_venda: "Pós-venda",
};
const SENTIMENT: Record<string, string> = {
  positivo: "Positivo",
  neutro: "Neutro",
  negativo: "Negativo",
};

/** Nomes dos tipos de alerta e rótulos, na ordem em que aparecem nos filtros. */
export const TYPE_LABELS: Record<string, string> = {
  promessa_indevida: "Promessa indevida",
  informacao_enganosa: "Informação enganosa ou omissão",
  pressao_abusiva: "Pressão abusiva",
  pagamento_fora_canal: "Pagamento fora do canal",
  linguagem_inadequada: "Linguagem inadequada",
  dados_pessoais_indevidos: "Dados pessoais indevidos",
  pedido_pendente: "Pedido sem resposta",
  objecao_sem_resposta: "Objeção sem resposta",
  sinal_compra_ignorado: "Sinal de compra ignorado",
  lead_esfriando: "Lead esfriando",
  follow_up_ausente: "Follow-up ausente",
  demora_resposta: "Demora na resposta",
  tentativa_manipulacao: "Tentativa de manipular a análise",
  objecao_preco: "Objeção de preço",
  objecao_confianca: "Objeção de confiança",
  objecao_prazo: "Objeção de prazo",
  objecao_vou_pensar: "Objeção \"vou pensar\"",
  objecao_concorrente: "Objeção de concorrente",
  objecao_cancelamento: "Objeção de cancelamento",
  sinal_compra: "Sinal de compra",
  pedido_cliente: "Pedido do cliente",
};

/** Tipos que viram alerta (os demais são rótulos de mensagem). */
export const ALERT_TYPES = [
  "promessa_indevida",
  "informacao_enganosa",
  "pressao_abusiva",
  "pagamento_fora_canal",
  "linguagem_inadequada",
  "dados_pessoais_indevidos",
  "pedido_pendente",
  "objecao_sem_resposta",
  "sinal_compra_ignorado",
  "lead_esfriando",
  "follow_up_ausente",
  "demora_resposta",
  "tentativa_manipulacao",
] as const;

export const typeLabel = (value: string) => TYPE_LABELS[value] ?? value.replaceAll("_", " ");

export const severityLabel = (value: string) => SEVERITY[value] ?? value;
export const statusLabel = (value: string) => STATUS[value] ?? value;
export const roleLabel = (value: string) => ROLE[value] ?? value;
export const stageLabel = (value: string | null | undefined) => (value ? (STAGE[value] ?? value) : "—");
export const sentimentLabel = (value: string | null | undefined) =>
  value ? (SENTIMENT[value] ?? value) : "—";

export function formatScore(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : String(Math.round(value));
}

export function formatDateTime(iso: string, timeZone?: string): string {
  const text = new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  }).format(new Date(iso));
  return text.replace(", ", " ");
}

export function formatTime(iso: string): string {
  return new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function formatDay(iso: string): string {
  return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short", year: "numeric" }).format(
    new Date(iso),
  );
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  const minutes = Math.round((now.getTime() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "agora";
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `há ${hours} h`;
  const days = Math.round(hours / 24);
  return days === 1 ? "há 1 dia" : `há ${days} dias`;
}
