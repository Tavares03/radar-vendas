import type { ButtonHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

import { severityLabel, statusLabel } from "@/lib/format";

type Variant = "primary" | "secondary" | "quiet" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-tinta text-papel hover:bg-tinta-suave disabled:bg-grafite",
  secondary: "border border-linha-forte bg-folha text-tinta hover:border-tinta",
  quiet: "text-tinta-suave hover:text-tinta hover:bg-linha/50",
  danger: "border border-critico text-critico hover:bg-critico-marca",
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
      className={`inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${VARIANTS[variant]} ${className}`}
    />
  );
}

export function SelectField({
  label,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm text-grafite">
      {label}
      <select
        {...props}
        className="rounded-md border border-linha-forte bg-folha px-2 py-1.5 text-tinta"
      >
        {children}
      </select>
    </label>
  );
}

const SEVERITY_STYLE: Record<string, string> = {
  critico: "bg-critico",
  atencao: "bg-[#ffb703]",
  info: "bg-info",
};

/** Severidade: uma barra de cor (marca-texto) e o nome por extenso, nunca só a cor. */
export function SeverityTag({ severity }: { severity: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm font-medium">
      <span aria-hidden className={`h-3.5 w-1.5 rounded-sm ${SEVERITY_STYLE[severity] ?? "bg-grafite"}`} />
      {severityLabel(severity)}
    </span>
  );
}

const STATUS_STYLE: Record<string, string> = {
  aberto: "text-tinta",
  em_revisao: "text-atencao",
  confirmado: "text-critico",
  resolvido: "text-ok",
  falso_positivo: "text-grafite line-through decoration-1",
};

export function StatusTag({ status }: { status: string }) {
  return <span className={`text-sm ${STATUS_STYLE[status] ?? ""}`}>{statusLabel(status)}</span>;
}

export function Loading({ label = "Carregando…" }: { label?: string }) {
  return (
    <p role="status" className="py-10 text-center text-sm text-grafite">
      {label}
    </p>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "Não foi possível carregar.";
  return (
    <p role="alert" className="rounded-md border-l-4 border-critico bg-folha px-4 py-3 text-sm">
      {message}
    </p>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-linha-forte px-6 py-10 text-center">
      <p className="font-semibold">{title}</p>
      {children ? <div className="mt-1 text-sm text-grafite">{children}</div> : null}
    </div>
  );
}

export function PageTitle({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <h1 className="text-[1.75rem] leading-tight font-extrabold tracking-tight">{title}</h1>
      {children}
    </header>
  );
}
