"use client";

import { useState } from "react";

import { formatScore } from "@/lib/format";

type Week = { week_start: string; conversations: number; average_score: number | null; critical_alerts: number };

const W = 460;
const H = 200;
const LEFT = 30;
const RIGHT = 26;
const TOP = 16;
const BOTTOM = 28;
const TICKS = [0, 60, 80, 100];

function weekDay(week: Week) {
  return new Date(`${week.week_start}T12:00:00`);
}

function shortDate(week: Week) {
  return weekDay(week).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }).replace(".", "");
}

function describe(week: Week) {
  if (week.average_score === null) return "sem conversas";
  const conversations = `${week.conversations} ${week.conversations === 1 ? "conversa" : "conversas"}`;
  const critical = week.critical_alerts
    ? `, ${week.critical_alerts} ${week.critical_alerts === 1 ? "alerta crítico" : "alertas críticos"} em aberto`
    : "";
  return `nota ${formatScore(week.average_score)} em ${conversations}${critical}`;
}

/**
 * Nota média por semana. Semanas sem conversa ficam vazias (não viram zero) e a linha só liga
 * semanas vizinhas com dado. Semana com alerta crítico em aberto ganha o anel vermelho.
 */
export function WeeklyTrend({ weeks }: { weeks: Week[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const plotW = W - LEFT - RIGHT;
  const plotH = H - TOP - BOTTOM;
  const step = weeks.length > 1 ? plotW / (weeks.length - 1) : 0;
  const x = (index: number) => LEFT + (weeks.length > 1 ? index * step : plotW / 2);
  const y = (score: number) => TOP + plotH - (score / 100) * plotH;

  const segments: string[] = [];
  let current: string[] = [];
  weeks.forEach((week, index) => {
    if (week.average_score === null) {
      if (current.length > 1) segments.push(current.join(" "));
      current = [];
      return;
    }
    current.push(`${current.length ? "L" : "M"}${x(index).toFixed(1)} ${y(week.average_score).toFixed(1)}`);
  });
  if (current.length > 1) segments.push(current.join(" "));

  const withData = weeks.filter((w) => w.average_score !== null);
  const last = withData[withData.length - 1];
  const focused = hover !== null ? weeks[hover] : null;

  if (withData.length === 0) {
    return <p className="py-8 text-center text-sm text-grafite">Ainda não há conversas analisadas nestas semanas.</p>;
  }

  return (
    <figure>
      <div className="relative" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-label="Nota média por semana">
          {/* Faixa de "bom atendimento" (80 a 100), a mesma régua da nota. */}
          <rect x={LEFT} y={y(100)} width={plotW} height={y(80) - y(100)} fill="var(--color-ok-marca)" opacity="0.45" />
          {TICKS.map((tick) => (
            <g key={tick}>
              <line
                x1={LEFT}
                x2={W - RIGHT}
                y1={y(tick)}
                y2={y(tick)}
                stroke="var(--color-linha)"
                strokeDasharray={tick === 0 ? undefined : "2 4"}
              />
              <text x={LEFT - 8} y={y(tick) + 4} textAnchor="end" fontSize="12" fill="var(--color-grafite)" className="numeros">
                {tick}
              </text>
            </g>
          ))}
          {weeks.map((week, index) =>
            index % 2 === (weeks.length - 1) % 2 ? (
              <text key={week.week_start} x={x(index)} y={H - 8} textAnchor="middle" fontSize="12" fill="var(--color-grafite)">
                {shortDate(week)}
              </text>
            ) : null,
          )}
          {focused ? (
            <line x1={x(hover as number)} x2={x(hover as number)} y1={TOP} y2={TOP + plotH} stroke="var(--color-linha-forte)" />
          ) : null}
          {segments.map((d) => (
            <path key={d} d={d} fill="none" stroke="var(--color-tinta)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {weeks.map((week, index) =>
            week.average_score === null ? null : (
              <g key={week.week_start}>
                {week.critical_alerts ? (
                  <circle cx={x(index)} cy={y(week.average_score)} r="8.5" fill="none" stroke="var(--color-critico)" strokeWidth="2" />
                ) : null}
                <circle
                  cx={x(index)}
                  cy={y(week.average_score)}
                  r={hover === index ? 5.5 : 4.5}
                  fill="var(--color-tinta)"
                  stroke="var(--color-folha)"
                  strokeWidth="2"
                />
              </g>
            ),
          )}
          {last && hover === null ? (
            <text
              x={x(weeks.indexOf(last))}
              y={y(last.average_score as number) - 14}
              textAnchor="end"
              fontSize="14"
              fontWeight="700"
              fill="var(--color-tinta)"
              className="numeros"
              dx="6"
            >
              {formatScore(last.average_score)}
            </text>
          ) : null}
          {/* Alvos de foco e de ponteiro, maiores que o ponto. */}
          {weeks.map((week, index) => (
            <rect
              key={week.week_start}
              x={x(index) - (step || plotW) / 2}
              y={TOP}
              width={step || plotW}
              height={plotH}
              fill="transparent"
              tabIndex={0}
              aria-label={`Semana de ${shortDate(week)}: ${describe(week)}`}
              onMouseEnter={() => setHover(index)}
              onFocus={() => setHover(index)}
              onBlur={() => setHover(null)}
              style={{ outline: "none" }}
            />
          ))}
        </svg>
        {focused ? (
          <div
            role="status"
            className="pointer-events-none absolute top-0 z-10 w-max max-w-56 -translate-x-1/2 rounded-lg bg-tinta px-3 py-2 text-xs text-papel shadow-lg"
            style={{ left: `${Math.min(82, Math.max(18, (x(hover as number) / W) * 100))}%` }}
          >
            <p className="font-semibold">Semana de {shortDate(focused)}</p>
            <p className="mt-0.5 text-papel/85">{describe(focused)}</p>
          </div>
        ) : null}
      </div>
      <figcaption className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-grafite">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="inline-block size-3 rounded-full border-2 border-critico" />
          semana com alerta crítico em aberto
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-2.5 w-4 rounded-sm bg-ok-marca" />
          faixa de bom atendimento (80 ou mais)
        </span>
      </figcaption>
      {/* A tabela dentro de um bloco: sozinha, ela ignora a largura de `sr-only` e estoura a página. */}
      <div className="sr-only">
        <table>
          <caption>Nota média por semana</caption>
          <thead>
            <tr>
              <th>Semana</th>
              <th>Resultado</th>
            </tr>
          </thead>
          <tbody>
            {weeks.map((week) => (
              <tr key={week.week_start}>
                <td>{shortDate(week)}</td>
                <td>{describe(week)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}
