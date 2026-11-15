"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { AlertReview } from "@/components/alert-review";
import { EvidenceInContext } from "@/components/evidence-in-context";
import { Button, Empty, ErrorNote, Loading, PageTitle, SelectField, SeverityTag, StatusTag } from "@/components/ui";
import type { Schemas } from "@/lib/api/client";
import { can, useAlerts, useMe, useSellers, useAssignees } from "@/lib/api/hooks";
import { ALERT_TYPES, relativeTime, typeLabel } from "@/lib/format";

const PAGE = 25;

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

  function setFilter(name: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(name, value);
    else next.delete(name);
    setLimit(PAGE);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  return (
    <>
      <PageTitle title="Alertas" />
      <div className="mb-5 flex flex-wrap gap-3">
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
          <p className="mb-2 text-sm text-grafite">
            {data.total} alerta{data.total === 1 ? "" : "s"}, os mais graves primeiro.
          </p>
          <ul className="divide-y divide-linha border-y border-linha bg-folha">
            {data.items.map((alert) => {
              const expanded = openId === alert.id;
              return (
                <li key={alert.id} className="px-4 py-3">
                  <button
                    type="button"
                    className="w-full text-left"
                    aria-expanded={expanded}
                    onClick={() => setOpenId(expanded ? null : alert.id)}
                  >
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
                      <SeverityTag severity={alert.severity} />
                      <span className="font-semibold">{alert.label}</span>
                      <span className="text-grafite">
                        {alert.seller_name ?? "Vendedor não identificado"} com {alert.customer_label}
                      </span>
                      <span className="ml-auto flex items-baseline gap-3">
                        <StatusTag status={alert.status} />
                        <span className="text-xs text-grafite">{relativeTime(alert.created_at)}</span>
                      </span>
                    </div>
                    <blockquote className="mt-1.5 max-w-3xl leading-relaxed">
                      <EvidenceInContext alert={alert} />
                    </blockquote>
                    {alert.contested ? (
                      <p className="mt-1 text-xs text-atencao">A regra apontou e o LLM discordou: vale olhar com cuidado.</p>
                    ) : null}
                  </button>
                  {expanded ? (
                    <div className="mt-3 space-y-3">
                      <p className="max-w-3xl text-sm">{alert.explanation}</p>
                      <Link
                        href={`/conversas/${alert.conversation_id}${alert.message_id ? `#m-${alert.message_id}` : ""}`}
                        className="inline-block text-sm font-medium underline underline-offset-2"
                      >
                        Abrir a conversa neste trecho
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
            <div className="mt-4 text-center">
              <Button onClick={() => setLimit((current) => current + PAGE)}>Carregar mais</Button>
            </div>
          ) : null}
        </>
      ) : null}
    </>
  );
}
