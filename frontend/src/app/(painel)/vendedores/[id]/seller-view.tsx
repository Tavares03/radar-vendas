"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { WeeklyTrend } from "@/components/trend";
import {
  ErrorNote,
  Initials,
  Loading,
  Meter,
  Panel,
  ScoreBadge,
  SectionTitle,
  SeverityTag,
} from "@/components/ui";
import { useSellerPerformance } from "@/lib/api/hooks";
import { formatDateTime, formatScore, plural } from "@/lib/format";

export function SellerView() {
  const { id } = useParams<{ id: string }>();
  const { data, error } = useSellerPerformance(id);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;

  const criteria = [...data.criteria].sort(
    (a, b) => a.average_points / a.maximum - b.average_points / b.maximum,
  );
  return (
    <>
      <Link href="/vendedores" className="inline-flex items-center gap-1 text-sm text-grafite hover:text-tinta">
        <ChevronLeft aria-hidden size={15} /> Vendedores
      </Link>
      <header className="mt-2 mb-7 flex flex-wrap items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3.5">
          <Initials name={data.seller.display_name} className="size-12 text-base" />
          <div className="min-w-0">
            <h1 className="text-[2rem] leading-[1.1] font-extrabold">{data.seller.display_name}</h1>
            <p className="mt-1 text-sm text-grafite">
              {plural(data.conversations, "conversa analisada", "conversas analisadas")}
            </p>
          </div>
        </div>
        <p className="flex items-center gap-3">
          <span className="text-right text-sm leading-tight text-grafite">
            nota
            <br />
            média
          </span>
          <ScoreBadge score={data.average_score} size="lg" />
        </p>
      </header>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Panel aria-labelledby="evolucao" className="p-5">
          <SectionTitle id="evolucao">Evolução</SectionTitle>
          <WeeklyTrend weeks={data.weekly} />
        </Panel>

        <Panel aria-labelledby="criterios" className="p-5">
          <SectionTitle id="criterios">Onde ganha e onde perde pontos</SectionTitle>
          {criteria.length ? (
            <ul className="space-y-3">
              {criteria.map((criterion) => (
                <li key={criterion.id} className="text-sm">
                  <div className="mb-1.5 flex justify-between gap-3">
                    <span className="font-medium">{criterion.label}</span>
                    <span className="numeros text-grafite">
                      {formatScore(criterion.average_points)} de {criterion.maximum}
                    </span>
                  </div>
                  <Meter value={criterion.average_points} maximum={criterion.maximum} label={criterion.label} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-grafite">Ainda não há conversas analisadas.</p>
          )}
        </Panel>

        <Panel aria-labelledby="objecoes" className="p-5">
          <SectionTitle id="objecoes">Objeções que enfrentou</SectionTitle>
          {data.objections.length ? (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-linha text-xs text-grafite">
                <tr>
                  <th className="py-2 font-medium">Objeção</th>
                  <th className="py-2 text-right font-medium">Bem</th>
                  <th className="py-2 text-right font-medium">Parcial</th>
                  <th className="py-2 text-right font-medium">Mal ou sem resposta</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-linha">
                {data.objections.map((item) => (
                  <tr key={item.type}>
                    <td className="py-2">{item.label}</td>
                    <td className="numeros py-2 text-right">{item.bem}</td>
                    <td className="numeros py-2 text-right">{item.parcial}</td>
                    <td
                      className={`numeros py-2 text-right ${item.mal + item.sem_resposta ? "font-bold text-critico" : ""}`}
                    >
                      {item.mal + item.sem_resposta}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-sm text-grafite">Nenhuma objeção registrada.</p>
          )}
        </Panel>

        <Panel aria-labelledby="riscos" className="p-5">
          <SectionTitle id="riscos">Alertas em aberto</SectionTitle>
          {data.alerts_by_type.length ? (
            <ul className="divide-y divide-linha text-sm">
              {data.alerts_by_type.map((item) => (
                <li key={item.type}>
                  <Link
                    href={`/alertas?seller=${data.seller.id}&type=${item.type}`}
                    className="group flex justify-between gap-3 py-2"
                  >
                    <span className="group-hover:underline">{item.label}</span>
                    <span className="numeros font-semibold">{item.count}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-grafite">Nenhum alerta em aberto.</p>
          )}
          {data.improvements.length ? (
            <>
              <h3 className="mt-5 font-bold">Pontos a melhorar</h3>
              <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm leading-relaxed marker:text-grafite">
                {data.improvements.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            </>
          ) : null}
        </Panel>
      </div>

      <section aria-labelledby="recentes" className="mt-8">
        <SectionTitle id="recentes">Conversas recentes</SectionTitle>
        <Panel>
          <ul className="divide-y divide-linha">
            {data.recent.map((conversation) => (
              <li key={conversation.id}>
                <Link
                  href={`/conversas/${conversation.id}`}
                  className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-sm hover:bg-papel/60"
                >
                  <span className="font-semibold">{conversation.customer_label}</span>
                  <span className="numeros text-grafite">
                    {conversation.last_message_at ? formatDateTime(conversation.last_message_at) : ""}
                  </span>
                  <span className="ml-auto flex items-center gap-3">
                    {conversation.max_severity ? <SeverityTag severity={conversation.max_severity} /> : null}
                    <ScoreBadge score={conversation.score} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
      </section>
    </>
  );
}
