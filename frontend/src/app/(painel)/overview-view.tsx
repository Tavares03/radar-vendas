"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { EvidenceInContext } from "@/components/evidence-in-context";
import { WeeklyTrend } from "@/components/trend";
import { Empty, ErrorNote, Loading, PageTitle, SelectField, SeverityTag } from "@/components/ui";
import { can, useAlerts, useMe, useOverview } from "@/lib/api/hooks";
import { formatDay, formatScore } from "@/lib/format";

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`;
}

export function OverviewView() {
  const { data: me } = useMe();
  const router = useRouter();
  const [days, setDays] = useState(30);
  const allowed = can(me, "analisar");
  // Só busca os indicadores de quem pode vê-los (o vendedor vai direto para as conversas).
  const { data, error } = useOverview(days, allowed);
  const critical = useAlerts({ severity: "critico", open_only: true, limit: 5 });

  useEffect(() => {
    if (me && !can(me, "analisar")) router.replace("/conversas");
  }, [me, router]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;

  const open = data.open_alerts;
  return (
    <>
      <PageTitle title="Visão geral">
        <SelectField label="Período" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={30}>30 dias</option>
          <option value={90}>90 dias</option>
          <option value={180}>180 dias</option>
        </SelectField>
      </PageTitle>

      {data.conversations_analyzed === 0 ? (
        <Empty title="Nenhuma conversa analisada no período">
          <Link href="/conversas" className="underline">
            Importe um export do WhatsApp
          </Link>{" "}
          para ver riscos, notas e a evolução da equipe.
        </Empty>
      ) : (
        <>
          <p className="max-w-3xl text-xl leading-snug">
            Até {formatDay(data.reference_date)}, nos últimos {days} dias:{" "}
            <strong>{plural(data.conversations_analyzed, "conversa analisada", "conversas analisadas")}</strong>, com
            nota média <strong className="numeros">{formatScore(data.average_score)}</strong>. Pedem atenção agora{" "}
            <strong className={open.critico ? "text-critico" : ""}>
              {plural(open.critico ?? 0, "alerta crítico", "alertas críticos")}
            </strong>{" "}
            e {plural(open.atencao ?? 0, "de atenção", "de atenção")} em todas as conversas.
          </p>

          <section aria-labelledby="criticos" className="mt-8">
            <div className="flex items-baseline justify-between gap-3">
              <h2 id="criticos" className="text-lg font-bold">
                O que precisa de você agora
              </h2>
              <Link href="/alertas" className="text-sm underline underline-offset-2">
                Ver todos os alertas
              </Link>
            </div>
            {critical.data?.items.length ? (
              <ol className="mt-3 divide-y divide-linha border-y border-linha">
                {critical.data.items.map((alert) => (
                  <li key={alert.id} className="py-3">
                    <Link
                      href={`/conversas/${alert.conversation_id}${alert.message_id ? `#m-${alert.message_id}` : ""}`}
                      className="group block"
                    >
                      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
                        <SeverityTag severity={alert.severity} />
                        <span className="font-semibold">{alert.label}</span>
                        <span className="text-grafite">
                          {alert.seller_name ?? "Vendedor não identificado"} com {alert.customer_label}
                        </span>
                      </div>
                      <blockquote className="mt-1.5 max-w-3xl text-[1.05rem] leading-relaxed">
                        <EvidenceInContext alert={alert} />
                      </blockquote>
                    </Link>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="mt-3 text-sm text-grafite">Nenhum alerta crítico em aberto. Bom sinal.</p>
            )}
          </section>

          <div className="mt-10 grid gap-10 lg:grid-cols-[1fr_1fr]">
            <section aria-labelledby="tendencia">
              <h2 id="tendencia" className="mb-3 text-lg font-bold">
                Nota média por semana
              </h2>
              <WeeklyTrend weeks={data.weekly} />
            </section>
            <section aria-labelledby="tipos">
              <h2 id="tipos" className="mb-3 text-lg font-bold">
                Alertas em aberto por tipo
              </h2>
              {data.alert_types.length ? (
                <ul className="space-y-2">
                  {data.alert_types.map((item) => {
                    const max = data.alert_types[0].count;
                    return (
                      <li key={item.type}>
                        <Link href={`/alertas?type=${item.type}`} className="flex items-center gap-3 text-sm hover:underline">
                          <span className="w-64 shrink-0 truncate">{item.label}</span>
                          <span className="h-2 flex-1 rounded-full bg-linha">
                            <span
                              className="block h-full rounded-full bg-tinta"
                              style={{ width: `${(item.count / max) * 100}%` }}
                            />
                          </span>
                          <span className="numeros w-8 text-right">{item.count}</span>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="text-sm text-grafite">Nenhum alerta em aberto.</p>
              )}
            </section>
          </div>

          <section aria-labelledby="equipe" className="mt-10">
            <h2 id="equipe" className="mb-3 text-lg font-bold">
              Equipe, da menor para a maior nota
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[32rem] text-left text-sm">
                <thead className="border-b border-linha-forte text-grafite">
                  <tr>
                    <th className="py-2 font-medium">Vendedor</th>
                    <th className="py-2 text-right font-medium">Conversas</th>
                    <th className="py-2 text-right font-medium">Nota média</th>
                    <th className="py-2 text-right font-medium">Alertas críticos</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-linha">
                  {data.sellers.map((seller) => (
                    <tr key={seller.seller_id}>
                      <td className="py-2.5">
                        <Link href={`/vendedores/${seller.seller_id}`} className="font-medium hover:underline">
                          {seller.name}
                        </Link>
                      </td>
                      <td className="numeros py-2.5 text-right">{seller.conversations}</td>
                      <td className="numeros py-2.5 text-right font-semibold">{formatScore(seller.average_score)}</td>
                      <td className={`numeros py-2.5 text-right ${seller.critical_alerts ? "font-semibold text-critico" : "text-grafite"}`}>
                        {seller.critical_alerts}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  );
}
