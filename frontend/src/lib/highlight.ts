/**
 * Divide o texto de uma mensagem em trechos para desenhar: texto comum, tarjas de dado pessoal
 * ([CPF], [TELEFONE]…) e marcas de evidência dos alertas (com a severidade).
 *
 * Tarjas são atômicas: uma evidência nunca corta uma tarja ao meio; a tarja fica dentro dela.
 */

export type Severity = "critico" | "atencao" | "info";

export type PiiSpan = { type: string; start: number; end: number };
export type EvidenceRange = { start: number; end: number; severity: Severity; alertId: string };

export type Segment =
  | { kind: "texto"; text: string }
  | { kind: "tarja"; text: string; insideEvidence?: Severity }
  | { kind: "evidencia"; text: string; severity: Severity; alertIds: string[] };

const RANK: Record<Severity, number> = { info: 0, atencao: 1, critico: 2 };

function strongest(ranges: EvidenceRange[]): Severity {
  return ranges.reduce<Severity>(
    (best, r) => (RANK[r.severity] > RANK[best] ? r.severity : best),
    "info",
  );
}

export function segment(text: string, pii: PiiSpan[], evidence: EvidenceRange[]): Segment[] {
  const length = text.length;
  const clamp = (n: number) => Math.max(0, Math.min(length, n));
  const spans = pii
    .map((p) => ({ ...p, start: clamp(p.start), end: clamp(p.end) }))
    .filter((p) => p.end > p.start);
  const marks = evidence
    .map((e) => ({ ...e, start: clamp(e.start), end: clamp(e.end) }))
    .filter((e) => e.end > e.start);

  const points = new Set<number>([0, length]);
  for (const item of [...spans, ...marks]) {
    points.add(item.start);
    points.add(item.end);
  }
  const ordered = [...points].sort((a, b) => a - b);

  const out: Segment[] = [];
  const emitted = new Set<PiiSpan>();
  for (let i = 0; i < ordered.length - 1; i += 1) {
    const [from, to] = [ordered[i], ordered[i + 1]];
    if (to <= from) continue;
    const span = spans.find((p) => p.start <= from && to <= p.end);
    if (span) {
      if (emitted.has(span)) continue;
      emitted.add(span);
      const around = marks.filter((e) => e.start < span.end && span.start < e.end);
      out.push(
        around.length
          ? { kind: "tarja", text: span.type, insideEvidence: strongest(around) }
          : { kind: "tarja", text: span.type },
      );
      continue;
    }
    const piece = text.slice(from, to);
    const covering = marks.filter((e) => e.start <= from && to <= e.end);
    const previous = out[out.length - 1];
    if (covering.length) {
      const severity = strongest(covering);
      const alertIds = covering.map((e) => e.alertId);
      if (
        previous?.kind === "evidencia" &&
        previous.severity === severity &&
        previous.alertIds.join() === alertIds.join()
      ) {
        previous.text += piece;
      } else {
        out.push({ kind: "evidencia", text: piece, severity, alertIds });
      }
    } else if (previous?.kind === "texto") {
      previous.text += piece;
    } else {
      out.push({ kind: "texto", text: piece });
    }
  }
  return out;
}

const PII_TYPES = [
  "CPF",
  "CNPJ",
  "RG",
  "TELEFONE",
  "EMAIL",
  "ENDERECO",
  "CEP",
  "PIX",
  "CONTA_BANCARIA",
  "PLACA",
  "NOME_PESSOA",
];
const PLACEHOLDER = new RegExp(`\\[(${PII_TYPES.join("|")})\\]`, "g");

/** Marcadores de máscara (`[CPF]`, `[NOME_PESSOA]`…) num texto já mascarado. */
export function placeholderSpans(text: string): PiiSpan[] {
  return Array.from(text.matchAll(PLACEHOLDER), (match) => ({
    type: match[1],
    start: match.index,
    end: match.index + match[0].length,
  }));
}

/** Minúsculas sem acento, com o mesmo comprimento (as posições continuam valendo). */
function fold(text: string): string {
  return Array.from(text)
    .map((ch) => ch.normalize("NFD")[0].toLowerCase())
    .join("");
}

/** Onde a evidência de um alerta aparece no texto da mensagem (ou ``null``). */
export function findEvidence(text: string, evidence: string): { start: number; end: number } | null {
  const needle = fold(evidence.replace(/…$/, "").trim());
  if (!needle) return null;
  const position = fold(text).indexOf(needle);
  return position < 0 ? null : { start: position, end: position + needle.length };
}
