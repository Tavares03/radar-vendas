import { CircleAlert, Info, TriangleAlert } from "lucide-react";
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

import { formatScore, severityLabel, statusLabel } from "@/lib/format";

import { RadarMark } from "./radar-mark";

type Variant = "primary" | "secondary" | "quiet" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-tinta text-papel shadow-sm hover:bg-tinta-suave disabled:bg-grafite",
  secondary: "border border-linha-forte bg-folha text-tinta hover:border-tinta",
  quiet: "text-tinta-suave hover:text-tinta hover:bg-linha/60",
  danger: "border border-critico/60 bg-folha text-critico hover:bg-critico-marca",
};

export function Button({
  variant = "secondary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-55 ${VARIANTS[variant]} ${className}`}
    />
  );
}

export const FIELD =
  "rounded-lg border border-linha-forte bg-folha px-3 py-2 text-sm text-tinta transition-colors hover:border-grafite";

export function SelectField({
  label,
  children,
  className = "",
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-[0.8rem] font-medium text-grafite">
      {label}
      <select {...props} className={`campo-select ${FIELD} ${className}`}>
        {children}
      </select>
    </label>
  );
}

const SEVERITY: Record<string, { chip: string; icon: typeof Info }> = {
  critico: { chip: "bg-critico-marca text-critico", icon: CircleAlert },
  atencao: { chip: "bg-atencao-marca text-atencao", icon: TriangleAlert },
  info: { chip: "bg-info-marca text-info", icon: Info },
};

/** Severidade: cor de marca-texto, ícone e o nome por extenso (nunca só a cor). */
export function SeverityTag({ severity }: { severity: string }) {
  const style = SEVERITY[severity];
  const Icon = style?.icon ?? Info;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-bold whitespace-nowrap ${style?.chip ?? "bg-linha text-grafite"}`}
    >
      <Icon aria-hidden size={13} strokeWidth={2.4} />
      {severityLabel(severity)}
    </span>
  );
}

const STATUS_STYLE: Record<string, string> = {
  aberto: "border-linha-forte text-tinta",
  em_revisao: "border-atencao-forte/60 text-atencao",
  confirmado: "border-critico/50 text-critico",
  resolvido: "border-ok/40 text-ok",
  falso_positivo: "border-linha text-grafite line-through decoration-1",
};

export function StatusTag({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${STATUS_STYLE[status] ?? "border-linha"}`}
    >
      {statusLabel(status)}
    </span>
  );
}

/** Faixa da nota: a mesma régua em todo o painel (80+ bom, 60+ com ajustes, abaixo com problemas). */
export function scoreBand(score: number | null | undefined): "ok" | "atencao" | "critico" | "vazio" {
  if (score === null || score === undefined) return "vazio";
  if (score >= 80) return "ok";
  if (score >= 60) return "atencao";
  return "critico";
}

const BAND_CHIP: Record<string, string> = {
  ok: "bg-ok-marca text-ok",
  atencao: "bg-atencao-marca text-atencao",
  critico: "bg-critico-marca text-critico",
  vazio: "bg-linha/70 text-grafite",
};

/** A nota num selo: o número é o dado, a cor diz a faixa. */
export function ScoreBadge({ score, size = "md" }: { score: number | null | undefined; size?: "md" | "lg" }) {
  const dims = size === "lg" ? "min-w-12 px-2.5 py-1 text-lg" : "min-w-9 px-2 py-0.5 text-sm";
  return (
    <span
      className={`numeros inline-flex justify-center rounded-md font-display font-bold ${dims} ${BAND_CHIP[scoreBand(score)]}`}
    >
      {formatScore(score)}
    </span>
  );
}

/** Iniciais de uma pessoa, para dar rosto às listas de equipe. */
export function Initials({ name, className = "" }: { name: string; className?: string }) {
  const parts = name.replace(/[^\p{L}\s]/gu, " ").trim().split(/\s+/);
  const letters = ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts[parts.length - 1][0] ?? "") : "")).toUpperCase();
  return (
    <span
      aria-hidden
      className={`inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-tinta text-xs font-bold tracking-wide text-papel ${className}`}
    >
      {letters || "?"}
    </span>
  );
}

/** Uma folha sobre a mesa: agrupa o que é lido junto (uma tabela, um gráfico, um formulário). */
export function Panel({
  className = "",
  children,
  ...props
}: HTMLAttributes<HTMLElement> & { children: ReactNode }) {
  return (
    <section {...props} className={`rounded-xl border border-linha bg-folha shadow-folha ${className}`}>
      {children}
    </section>
  );
}

export function Loading({ label = "Carregando…" }: { label?: string }) {
  return (
    <p role="status" className="flex items-center justify-center gap-2.5 py-14 text-sm text-grafite">
      <RadarMark size={20} animated className="text-grafite" />
      {label}
    </p>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "Não foi possível carregar.";
  return (
    <p
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-critico/30 bg-critico-marca/40 px-4 py-3 text-sm"
    >
      <CircleAlert aria-hidden size={17} className="mt-0.5 shrink-0 text-critico" />
      {message}
    </p>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-linha-forte bg-folha/60 px-6 py-12 text-center">
      <RadarMark size={36} className="mx-auto mb-3 text-grafite" />
      <p className="font-display text-lg font-bold">{title}</p>
      {children ? <div className="mx-auto mt-1 max-w-md text-sm text-grafite">{children}</div> : null}
    </div>
  );
}

export function PageTitle({
  title,
  lead,
  children,
}: {
  title: string;
  lead?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="text-[2rem] leading-[1.1] font-extrabold">{title}</h1>
        {lead ? <p className="mt-1.5 max-w-2xl text-sm text-grafite">{lead}</p> : null}
      </div>
      {children}
    </header>
  );
}

/** Título de seção dentro de uma página. */
export function SectionTitle({ id, children, aside }: { id?: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
      <h2 id={id} className="text-lg font-bold">
        {children}
      </h2>
      {aside}
    </div>
  );
}

/** Barra de proporção (pontos de um critério, parcela de um total). */
export function Meter({
  value,
  maximum,
  label,
  tone,
}: {
  value: number;
  maximum: number;
  label: string;
  tone?: "tinta" | "ok" | "atencao" | "critico";
}) {
  const ratio = maximum ? Math.min(1, Math.max(0, value / maximum)) : 1;
  const auto = ratio >= 0.8 ? "ok" : ratio >= 0.5 ? "atencao" : "critico";
  const color = { tinta: "bg-tinta", ok: "bg-ok", atencao: "bg-atencao-forte", critico: "bg-critico" }[tone ?? auto];
  return (
    <div
      className="h-1.5 overflow-hidden rounded-full bg-linha"
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={maximum}
      aria-valuenow={value}
    >
      <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.max(ratio ? 3 : 0, ratio * 100)}%` }} />
    </div>
  );
}
