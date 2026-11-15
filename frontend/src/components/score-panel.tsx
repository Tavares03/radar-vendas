import type { Schemas } from "@/lib/api/client";
import { formatScore } from "@/lib/format";

import { Meter, scoreBand } from "./ui";

type Criterion = Schemas["CriterionOut"];

const BAND = {
  ok: { label: "Bom atendimento", tone: "text-ok", stroke: "var(--color-ok)" },
  atencao: { label: "Atendimento com ajustes", tone: "text-atencao", stroke: "var(--color-atencao-forte)" },
  critico: { label: "Atendimento com problemas", tone: "text-critico", stroke: "var(--color-critico)" },
  vazio: { label: "Sem nota", tone: "text-grafite", stroke: "var(--color-linha-forte)" },
};

const R = 52;
const ARC = Math.PI * R;

/** Nota explicável: o número num arco de 0 a 100 e, embaixo, de onde cada ponto veio. */
export function ScorePanel({ score, criteria }: { score: number; criteria: Criterion[] }) {
  const { label, tone, stroke } = BAND[scoreBand(score)];
  const estimated = criteria.some((c) => c.estimated);
  const ratio = Math.min(1, Math.max(0, score / 100));
  return (
    <section aria-labelledby="nota-titulo">
      <h2 id="nota-titulo" className="sr-only">
        Nota do atendimento
      </h2>
      <div className="relative mx-auto w-48">
        <svg aria-hidden viewBox="0 0 120 68" className="block w-full">
          <path
            d={`M8 62 A${R} ${R} 0 0 1 112 62`}
            fill="none"
            stroke="var(--color-linha)"
            strokeWidth="9"
            strokeLinecap="round"
          />
          <path
            d={`M8 62 A${R} ${R} 0 0 1 112 62`}
            fill="none"
            stroke={stroke}
            strokeWidth="9"
            strokeLinecap="round"
            strokeDasharray={`${ARC * ratio} ${ARC}`}
          />
        </svg>
        <p className="absolute inset-x-0 bottom-0 flex items-baseline justify-center gap-1">
          <span className="numeros font-display text-[2.9rem] leading-none font-extrabold">{formatScore(score)}</span>
          <span className="text-sm text-grafite">/100</span>
        </p>
      </div>
      <p className={`mt-2 text-center font-semibold ${tone}`}>{label}</p>
      <dl className="mt-5 space-y-3.5">
        {criteria.map((criterion) => (
          <div key={criterion.id}>
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <dt className="font-semibold">
                {criterion.label}
                {criterion.estimated ? <span className="font-normal text-grafite"> (estimado)</span> : null}
              </dt>
              <dd className="numeros shrink-0 text-grafite">
                {formatScore(criterion.points)} de {criterion.maximum}
              </dd>
            </div>
            <div className="mt-1.5">
              <Meter value={criterion.points} maximum={criterion.maximum} label={criterion.label} />
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-grafite">{criterion.justification}</p>
          </div>
        ))}
      </dl>
      {estimated ? (
        <p className="mt-4 rounded-lg bg-papel px-3 py-2 text-xs leading-relaxed text-grafite">
          Critérios estimados foram avaliados sem o LLM. Configure uma chave gratuita ou o Ollama
          para avaliar objeções e pedidos com mais precisão.
        </p>
      ) : null}
    </section>
  );
}
