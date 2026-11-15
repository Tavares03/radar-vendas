"use client";

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { EvidenceInContext } from "@/components/evidence-in-context";
import { WeeklyTrend } from "@/components/trend";
import {
  Empty,
  ErrorNote,
  Initials,
  Loading,
  PageTitle,
  Panel,
  ScoreBadge,
  scoreBand,
  SectionTitle,
  SeverityTag,
} from "@/components/ui";
import { can, useAlerts, useMe, useOverview } from "@/lib/api/hooks";
import { formatDay, formatScore, plural } from "@/lib/format";

const PERIODS = [30, 90, 180];

function PeriodSwitch({ days, onChange }: { days: number; onChange: (days: number) => void }) {
  return (
    <div role="group" aria-label="Período" className="inline-flex rounded-lg border border-linha-forte bg-folha p-0.5">
      {PERIODS.map((value) => (
        <button
          key={value}
          type="button"
          aria-pressed={days === value}
          onClick={() => onChange(value)}
          className={`rounded-md px-3 py-1.5 text-sm font-semibold transition-colors ${
            days === value ? "bg-tinta text-papel" : "text-grafite hover:text-tinta"
          }`}
        >
          {value} dias
        </button>
      ))}
    </div>
  );
}

export function OverviewView() {
  const { data: me } = useMe();
  const router = useRouter();
  const [days, setDays] = useState(30);
  const allowed = can(me, "analisar");
  // Só busca os indicadores de quem pode vê-los (o vendedor vai direto para as conversas).
  const { data, error } = useOverview(days, allowed);
  const critical = useAlerts({ severity: "critico", open_only: true, limit: 5 }, allowed);

  useEffect(() => {
    if (me && !can(me, "analisar")) router.replace("/conversas");
  }, [me, router]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;

  const open = data.open_alerts;
  const band = scoreBand(data.average_score);
  const maxType = data.alert_types[0]?.count ?? 1;
  return (
    <>
      <PageTitle title="Visão geral">
        <PeriodSwitch days={days} onChange={setDays} />
      </PageTitle>

      {data.conversations_analyzed === 0 ? (
        <Empty title="Nenhuma conversa analisada no período">
          <Link href="/conversas" className="font-medium underline underline-offset-2">
            Importe um export do WhatsApp
          </Link>{" "}
          para ver riscos, notas e a evolução da equipe.
        </Empty>
      ) : (
        <>
          <p className="max-w-4xl font-display text-[1.6rem] leading-[1.35] font-medium text-tinta-suave sm:text-[1.9rem]">
            Nos {days} dias até {formatDay(data.reference_date)}, o Radar leu{" "}
            <strong className="font-bold text-tinta">
              {plural(data.conversations_analyzed, "conversa", "conversas")}
            </strong>{" "}
            e a nota média ficou em{" "}
            <strong className="marca numeros font-bold text-tinta" data-severity={band === "vazio" ? "info" : band}>
              {formatScore(data.average_score)}
            </strong>
            . Esperam por você{" "}
            <strong className="marca font-bold text-tinta" data-severity={open.critico ? "critico" : "ok"}>
              {plural(open.critico ?? 0, "alerta crítico", "alertas críticos")}
            </strong>{" "}
            e{" "}
            <strong className="marca font-bold text-tinta" data-severity={open.atencao ? "atencao" : "ok"}>
              {open.atencao ?? 0} de atenção
            </strong>
            .
          </p>

          <div className="mt-9 grid items-start gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
            <section aria-labelledby="criticos" className="min-w-0">
              <SectionTitle
                id="criticos"
                aside={
                  <Link href="/alertas" className="text-sm font-medium text-tinta-suave underline underline-offset-2 hover:text-tinta">
                    Ver todos os alertas
                  </Link>
                }
              >
                O que precisa de você agora
              </SectionTitle>
              {critical.data?.items.length ? (
                <ol className="space-y-2.5">
                  {critical.data.items.map((alert) => (
                    <li key={alert.id}>
                      <Link
                        href={`/conversas/${alert.conversation_id}${alert.message_id ? `#m-${alert.message_id}` : ""}`}
                        className="group block rounded-xl border border-linha border-l-4 border-l-critico bg-folha px-4 py-3 shadow-folha transition-colors hover:border-linha-forte hover:border-l-critico"
                      >
                        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm">
                          <SeverityTag severity={alert.severity} />
                          <span className="font-bold">{alert.label}</span>
                          <ArrowUpRight
                            aria-hidden
                            size={16}
                            className="ml-auto text-grafite transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-tinta"
                          />
                        </div>
                        <blockquote className="mt-2 text-[1.05rem] leading-relaxed">
                          <EvidenceInContext alert={alert} />
                        </blockquote>
                        <p className="mt-1.5 text-xs text-grafite">
                          {alert.seller_name ?? "Vendedor não identificado"} com {alert.customer_label}
                        </p>
                      </Link>
                    </li>
                  ))}
                </ol>
              ) : (
                <Panel className="px-4 py-8 text-center text-sm text-grafite">
                  Nenhum alerta crítico em aberto. Bom sinal.
                </Panel>
              )}
            </section>

            <div className="min-w-0 space-y-6">
              <Panel aria-labelledby="tendencia" className="p-5">
                <SectionTitle id="tendencia">Nota média por semana</SectionTitle>
                <WeeklyTrend weeks={data.weekly} />
              </Panel>
              <Panel aria-labelledby="tipos" className="p-5">
                <SectionTitle id="tipos">Alertas em aberto por tipo</SectionTitle>
                {data.alert_types.length ? (
                  <ul className="space-y-2.5">
                    {data.alert_types.map((item) => (
                      <li key={item.type}>
                        <Link href={`/alertas?type=${item.type}`} className="group block text-sm">
                          <span className="flex items-baseline justify-between gap-3">
                            <span className="truncate group-hover:underline">{item.label}</span>
                            <span className="numeros font-semibold">{item.count}</span>
                          </span>
                          <span className="mt-1 block h-1.5 rounded-full bg-linha">
                            <span
                              className="block h-full rounded-full bg-tinta"
                              style={{ width: `${(item.count / maxType) * 100}%` }}
                            />
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-grafite">Nenhum alerta em aberto.</p>
                )}
              </Panel>
            </div>
          </div>

          <section aria-labelledby="equipe" className="mt-9">
            <SectionTitle
              id="equipe"
              aside={<span className="text-sm text-grafite">quem mais precisa de apoio aparece primeiro</span>}
            >
              Equipe
            </SectionTitle>
            <Panel className="overflow-x-auto">
              <table className="w-full min-w-[34rem] text-left text-sm">
                <thead className="border-b border-linha text-xs text-grafite">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Vendedor</th>
                    <th className="px-4 py-2.5 text-right font-medium">Conversas</th>
                    <th className="px-4 py-2.5 text-right font-medium">Alertas críticos</th>
                    <th className="px-4 py-2.5 text-right font-medium">Nota média</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-linha">
                  {data.sellers.map((seller) => (
                    <tr key={seller.seller_id} className="hover:bg-papel/60">
                      <td className="px-4 py-2.5">
                        <Link
                          href={`/vendedores/${seller.seller_id}`}
                          className="flex items-center gap-2.5 font-semibold hover:underline"
                        >
                          <Initials name={seller.name} />
                          {seller.name}
                        </Link>
                      </td>
                      <td className="numeros px-4 py-2.5 text-right">{seller.conversations}</td>
                      <td
                        className={`numeros px-4 py-2.5 text-right ${seller.critical_alerts ? "font-bold text-critico" : "text-grafite"}`}
                      >
                        {seller.critical_alerts}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <ScoreBadge score={seller.average_score} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </section>
        </>
      )}
    </>
  );
}
