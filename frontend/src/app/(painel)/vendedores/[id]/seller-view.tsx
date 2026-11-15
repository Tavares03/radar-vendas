"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { WeeklyTrend } from "@/components/trend";
import { ErrorNote, Loading, PageTitle, SeverityTag } from "@/components/ui";
import { useSellerPerformance } from "@/lib/api/hooks";
import { formatDateTime, formatScore } from "@/lib/format";

export function SellerView() {
  const { id } = useParams<{ id: string }>();
  const { data, error } = useSellerPerformance(id);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;

  return (
    <>
      <Link href="/vendedores" className="text-sm text-grafite hover:text-tinta">
        Vendedores
      </Link>
      <PageTitle title={data.seller.display_name}>
        <p className="text-right">
          <span className="numeros block text-4xl leading-none font-extrabold">{formatScore(data.average_score)}</span>
          <span className="text-sm text-grafite">
            nota média em {data.conversations} {data.conversations === 1 ? "conversa" : "conversas"}
          </span>
        </p>
      </PageTitle>

      <div className="grid gap-10 lg:grid-cols-2">
        <section aria-labelledby="evolucao">
          <h2 id="evolucao" className="mb-3 text-lg font-bold">
            Evolução
          </h2>
          <WeeklyTrend weeks={data.weekly} />
        </section>

        <section aria-labelledby="criterios">
          <h2 id="criterios" className="mb-3 text-lg font-bold">
            Onde ganha e onde perde pontos
          </h2>
          <ul className="space-y-2">
            {[...data.criteria]
              .sort((a, b) => a.average_points / a.maximum - b.average_points / b.maximum)
              .map((criterion) => {
                const ratio = criterion.average_points / criterion.maximum;
                return (
                  <li key={criterion.id} className="text-sm">
                    <div className="flex justify-between">
                      <span>{criterion.label}</span>
                      <span className="numeros text-grafite">
                        {formatScore(criterion.average_points)} de {criterion.maximum}
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 rounded-full bg-linha">
                      <div
                        className={`h-full rounded-full ${ratio >= 0.8 ? "bg-tinta" : ratio >= 0.5 ? "bg-[#ffb703]" : "bg-critico"}`}
                        style={{ width: `${Math.max(2, ratio * 100)}%` }}
                      />
                    </div>
                  </li>
                );
              })}
          </ul>
        </section>

        <section aria-labelledby="objecoes">
          <h2 id="objecoes" className="mb-3 text-lg font-bold">
            Objeções que enfrentou
          </h2>
          {data.objections.length ? (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-linha-forte text-grafite">
                <tr>
                  <th className="py-1.5 font-medium">Objeção</th>
                  <th className="py-1.5 text-right font-medium">Bem</th>
                  <th className="py-1.5 text-right font-medium">Parcial</th>
                  <th className="py-1.5 text-right font-medium">Mal ou sem resposta</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-linha">
                {data.objections.map((item) => (
                  <tr key={item.type}>
                    <td className="py-1.5">{item.label}</td>
                    <td className="numeros py-1.5 text-right">{item.bem}</td>
                    <td className="numeros py-1.5 text-right">{item.parcial}</td>
                    <td className={`numeros py-1.5 text-right ${item.mal + item.sem_resposta ? "font-semibold text-critico" : ""}`}>
                      {item.mal + item.sem_resposta}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-sm text-grafite">Nenhuma objeção registrada.</p>
          )}
        </section>

        <section aria-labelledby="riscos">
          <h2 id="riscos" className="mb-3 text-lg font-bold">
            Alertas em aberto
          </h2>
          {data.alerts_by_type.length ? (
            <ul className="space-y-1 text-sm">
              {data.alerts_by_type.map((item) => (
                <li key={item.type} className="flex justify-between">
                  <Link href={`/alertas?seller=${data.seller.id}&type=${item.type}`} className="hover:underline">
                    {item.label}
                  </Link>
                  <span className="numeros">{item.count}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-grafite">Nenhum alerta em aberto.</p>
          )}
          {data.improvements.length ? (
            <>
              <h3 className="mt-5 font-bold">Pontos a melhorar</h3>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                {data.improvements.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            </>
          ) : null}
        </section>
      </div>

      <section aria-labelledby="recentes" className="mt-10">
        <h2 id="recentes" className="mb-3 text-lg font-bold">
          Conversas recentes
        </h2>
        <ul className="divide-y divide-linha border-y border-linha">
          {data.recent.map((conversation) => (
            <li key={conversation.id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-2.5 text-sm">
              <Link href={`/conversas/${conversation.id}`} className="font-semibold hover:underline">
                {conversation.customer_label}
              </Link>
              <span className="text-grafite">
                {conversation.last_message_at ? formatDateTime(conversation.last_message_at) : ""}
              </span>
              <span className="numeros ml-auto font-semibold">nota {formatScore(conversation.score)}</span>
              {conversation.max_severity ? <SeverityTag severity={conversation.max_severity} /> : null}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
