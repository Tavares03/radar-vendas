"use client";

import { ChevronDown } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { AlertReview } from "@/components/alert-review";
import { EvidenceInContext } from "@/components/evidence-in-context";
import { Button, Empty, ErrorNote, Loading, PageTitle, SelectField, SeverityTag, StatusTag } from "@/components/ui";
import type { Schemas } from "@/lib/api/client";
import { can, useAlerts, useMe, useSellers, useAssignees } from "@/lib/api/hooks";
import { ALERT_TYPES, plural, relativeTime, typeLabel } from "@/lib/format";

const PAGE = 25;

const STRIPE: Record<string, string> = {
  critico: "border-l-critico",
  atencao: "border-l-atencao-forte",
  info: "border-l-info",
};

export function AlertsView() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { data: me } = useMe();
  const sellers = useSellers();
  const users = useAssignees(can(me, "revisar"));
  const [limit, setLimit] = useState(PAGE);
  const [openId, setOpenId] = useState<string | null>(null);

  const severity = params.get("severity") ?? "";
  const type = params.get("type") ?? "";
  const status = params.get("status") ?? "abertos";
  const seller = params.get("seller") ?? "";
  const filters = {
    severity: severity || undefined,
    type: type || undefined,
    seller_id: seller || undefined,
    status: status && status !== "abertos" && status !== "todos" ? (status as Schemas["AlertStatus"]) : undefined,
    open_only: status === "abertos",
    limit,
  };
  const { data, error, mutate } = useAlerts(filters);
  const filtered = Boolean(severity || type || seller || status !== "abertos");

  function setFilter(name: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(name, value);
    else next.delete(name);
    setLimit(PAGE);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  return (
    <>
      <PageTitle
        title="Alertas"
        lead="Cada alerta aponta o trecho exato da conversa. Revise, marque o que for falso positivo e atribua um responsável."
      />
      <div className="mb-5 flex flex-wrap items-end gap-3">
        <SelectField label="Situação" value={status} onChange={(e) => setFilter("status", e.target.value)}>
          <option value="abertos">Pedem atenção</option>
          <option value="aberto">Abertos</option>
          <option value="em_revisao">Em revisão</option>
          <option value="confirmado">Confirmados</option>
          <option value="resolvido">Resolvidos</option>
          <option value="falso_positivo">Falsos positivos</option>
          <option value="todos">Todos</option>
        </SelectField>
        <SelectField label="Severidade" value={severity} onChange={(e) => setFilter("severity", e.target.value)}>
          <option value="">Todas</option>
          <option value="critico">Crítico</option>
          <option value="atencao">Atenção</option>
          <option value="info">Info</option>
        </SelectField>
        <SelectField label="Tipo" value={type} onChange={(e) => setFilter("type", e.target.value)}>
          <option value="">Todos</option>
          {ALERT_TYPES.map((value) => (
            <option key={value} value={value}>
              {typeLabel(value)}
            </option>
          ))}
        </SelectField>
        {sellers.data && sellers.data.length > 1 ? (
          <SelectField label="Vendedor" value={seller} onChange={(e) => setFilter("seller", e.target.value)}>
            <option value="">Todos</option>
            {sellers.data.map((s) => (
              <option key={s.id} value={s.id}>
                {s.display_name}
              </option>
            ))}
          </SelectField>
        ) : null}
        {filtered ? (
          <Button variant="quiet" onClick={() => router.replace(pathname, { scroll: false })}>
            Limpar filtros
          </Button>
        ) : null}
      </div>

      {error ? <ErrorNote error={error} /> : null}
      {!data && !error ? <Loading /> : null}
      {data && data.items.length === 0 ? (
        <Empty title="Nenhum alerta com esses filtros">
          Quando uma conversa importada tiver risco ou oportunidade perdida, ele aparece aqui.
        </Empty>
      ) : null}
      {data && data.items.length > 0 ? (
        <>
          <p className="mb-3 text-sm text-grafite">
            {plural(data.total, "alerta", "alertas")}, os mais graves primeiro.
          </p>
          <ul className="space-y-2.5">
            {data.items.map((alert) => {
              const expanded = openId === alert.id;
              return (
                <li
                  key={alert.id}
                  className={`rounded-xl border border-linha border-l-4 bg-folha shadow-folha ${STRIPE[alert.severity] ?? "border-l-linha-forte"}`}
                >
                  <button
                    type="button"
                    className="w-full rounded-xl px-4 py-3 text-left"
                    aria-expanded={expanded}
                    onClick={() => setOpenId(expanded ? null : alert.id)}
                  >
                    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-sm">
                      <SeverityTag severity={alert.severity} />
                      <span className="font-bold">{alert.label}</span>
                      <span className="ml-auto flex items-center gap-2.5">
                        <StatusTag status={alert.status} />
                        <ChevronDown
                          aria-hidden
                          size={17}
                          className={`text-grafite transition-transform ${expanded ? "rotate-180" : ""}`}
                        />
                      </span>
                    </div>
                    {alert.message_text || alert.evidence ? (
                      <blockquote className="mt-2 max-w-3xl text-[1.02rem] leading-relaxed">
                        <EvidenceInContext alert={alert} />
                      </blockquote>
                    ) : (
                      <p className="mt-2 max-w-3xl text-[0.95rem] leading-relaxed text-tinta-suave">{alert.explanation}</p>
                    )}
                    <p className="mt-1.5 text-xs text-grafite">
                      {alert.seller_name ?? "Vendedor não identificado"} com {alert.customer_label}, detectado{" "}
                      {relativeTime(alert.created_at)}
                      {alert.assigned_to ? `, com ${alert.assigned_to.name}` : ""}
                    </p>
                    {alert.contested ? (
                      <p className="mt-1 text-xs font-medium text-atencao">
                        A regra apontou e o LLM discordou: vale olhar com cuidado.
                      </p>
                    ) : null}
                  </button>
                  {expanded ? (
                    <div className="space-y-3 border-t border-linha px-4 pt-3 pb-4">
                      {alert.message_text || alert.evidence ? (
                        <p className="max-w-3xl text-sm text-tinta-suave">{alert.explanation}</p>
                      ) : null}
                      <Link
                        href={`/conversas/${alert.conversation_id}${alert.message_id ? `#m-${alert.message_id}` : ""}`}
                        className="inline-block text-sm font-semibold underline underline-offset-2"
                      >
                        {alert.message_id ? "Abrir a conversa neste trecho" : "Abrir a conversa"}
                      </Link>
                      {can(me, "revisar") ? (
                        <AlertReview
                          alert={alert}
                          users={users.data ?? []}
                          onSaved={() => {
                            void mutate();
                          }}
                        />
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
          {data.total > data.items.length ? (
            <div className="mt-5 text-center">
              <Button onClick={() => setLimit((current) => current + PAGE)}>Carregar mais</Button>
            </div>
          ) : null}
        </>
      ) : null}
    </>
  );
}
