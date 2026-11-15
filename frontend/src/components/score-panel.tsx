import type { Schemas } from "@/lib/api/client";
import { formatScore } from "@/lib/format";

type Criterion = Schemas["CriterionOut"];

function band(score: number): { label: string; tone: string } {
  if (score >= 80) return { label: "Bom atendimento", tone: "text-ok" };
  if (score >= 60) return { label: "Atendimento com ajustes", tone: "text-atencao" };
  return { label: "Atendimento com problemas", tone: "text-critico" };
}

/** Nota explicável: o número e, embaixo, de onde cada ponto veio. */
export function ScorePanel({ score, criteria }: { score: number; criteria: Criterion[] }) {
  const { label, tone } = band(score);
  const estimated = criteria.some((c) => c.estimated);
  return (
    <section aria-labelledby="nota-titulo">
      <h2 id="nota-titulo" className="sr-only">
        Nota do atendimento
      </h2>
      <div className="flex items-baseline gap-2">
        <span className="numeros text-6xl leading-none font-extrabold tracking-tight">{formatScore(score)}</span>
        <span className="text-lg text-grafite">/100</span>
      </div>
      <p className={`mt-1 font-semibold ${tone}`}>{label}</p>
      <dl className="mt-4 space-y-3">
        {criteria.map((criterion) => {
          const ratio = criterion.maximum ? criterion.points / criterion.maximum : 1;
          return (
            <div key={criterion.id}>
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <dt className="font-medium">
                  {criterion.label}
                  {criterion.estimated ? <span className="text-grafite"> (estimado)</span> : null}
                </dt>
                <dd className="numeros text-grafite">
                  {formatScore(criterion.points)} de {criterion.maximum}
                </dd>
              </div>
              <div
                className="mt-1 h-1.5 rounded-full bg-linha"
                role="meter"
                aria-label={criterion.label}
                aria-valuemin={0}
                aria-valuemax={criterion.maximum}
                aria-valuenow={criterion.points}
              >
                <div
                  className={`h-full rounded-full ${ratio >= 0.8 ? "bg-tinta" : ratio >= 0.5 ? "bg-[#ffb703]" : "bg-critico"}`}
                  style={{ width: `${Math.max(2, ratio * 100)}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-grafite">{criterion.justification}</p>
            </div>
          );
        })}
      </dl>
      {estimated ? (
        <p className="mt-4 text-xs text-grafite">
          Critérios estimados foram avaliados sem o LLM. Configure uma chave gratuita ou o Ollama
          para avaliar objeções e pedidos com mais precisão.
        </p>
      ) : null}
    </section>
  );
}
