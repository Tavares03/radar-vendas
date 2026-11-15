import { formatScore } from "@/lib/format";

type Week = { week_start: string; conversations: number; average_score: number | null; critical_alerts: number };

/** Nota média por semana: barras finas; semanas sem conversa ficam vazias (não viram zero). */
export function WeeklyTrend({ weeks }: { weeks: Week[] }) {
  const last = [...weeks].reverse().find((w) => w.average_score !== null);
  return (
    <figure>
      <div className="flex h-24 items-end gap-1.5" role="img" aria-label="Nota média por semana">
        {weeks.map((week) => {
          const height = week.average_score === null ? 0 : Math.max(4, week.average_score);
          const day = new Date(`${week.week_start}T12:00:00`);
          const label = `${day.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" })}: ${
            week.average_score === null ? "sem conversas" : `nota ${formatScore(week.average_score)}`
          }, ${week.critical_alerts} crítico(s)`;
          return (
            <div key={week.week_start} className="flex h-full flex-1 flex-col justify-end" title={label}>
              <div
                className={`rounded-t-sm ${week.critical_alerts ? "bg-critico" : "bg-tinta"} ${week.average_score === null ? "opacity-0" : ""}`}
                style={{ height: `${height}%` }}
              />
            </div>
          );
        })}
      </div>
      <figcaption className="mt-2 text-xs text-grafite">
        Últimas {weeks.length} semanas. Barras vermelhas tiveram alerta crítico em aberto.
        {last ? ` Última semana com conversas: nota ${formatScore(last.average_score)}.` : ""}
      </figcaption>
    </figure>
  );
}
