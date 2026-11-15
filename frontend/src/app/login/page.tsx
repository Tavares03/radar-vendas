import type { Metadata } from "next";

import { HighlightedText } from "@/components/highlighted-text";
import { RadarMark } from "@/components/radar-mark";
import { SeverityTag } from "@/components/ui";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Entrar" };

const SAMPLE = "Fica tranquilo, sua contemplação é garantida no terceiro mês. Me passa seu CPF [CPF]?";

/** A tela do radar ao fundo: anéis, a varredura girando e os pontos que ela encontra. */
function RadarScope() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 600 600"
      className="pointer-events-none absolute -right-40 -bottom-44 w-[44rem] max-w-none text-white"
      fill="none"
    >
      {[290, 220, 150, 80].map((r) => (
        <circle key={r} cx="300" cy="300" r={r} stroke="currentColor" strokeOpacity="0.09" strokeWidth="1.5" />
      ))}
      <path d="M10 300h580M300 10v580" stroke="currentColor" strokeOpacity="0.06" strokeWidth="1.5" />
      <g className="animate-varredura" style={{ transformOrigin: "300px 300px" }}>
        <path d="M300 300 L300 10 A290 290 0 0 1 551.1 155 Z" fill="var(--color-sinal)" fillOpacity="0.1" />
        <path d="M300 300 L300 10" stroke="var(--color-sinal)" strokeOpacity="0.7" strokeWidth="2" />
      </g>
      {[
        { x: 388, y: 170, color: "var(--color-critico)", delay: "0s" },
        { x: 438, y: 352, color: "var(--color-sinal)", delay: "0.9s" },
        { x: 250, y: 430, color: "var(--color-atencao-forte)", delay: "1.7s" },
      ].map((blip) => (
        <g key={`${blip.x}-${blip.y}`}>
          <circle
            cx={blip.x}
            cy={blip.y}
            r="9"
            fill={blip.color}
            className="animate-pulso"
            style={{ transformOrigin: `${blip.x}px ${blip.y}px`, animationDelay: blip.delay }}
          />
          <circle cx={blip.x} cy={blip.y} r="5" fill={blip.color} />
        </g>
      ))}
    </svg>
  );
}

export default function LoginPage() {
  return (
    <main className="grid min-h-screen lg:grid-cols-[minmax(0,1.15fr)_minmax(24rem,1fr)]">
      <section
        aria-label="O que o Radar faz"
        className="sobre-noite relative hidden flex-col justify-between overflow-hidden bg-noite px-14 py-12 text-white lg:flex"
      >
        <RadarScope />
        <p className="relative flex items-center gap-2.5 font-display text-lg font-bold">
          <RadarMark size={30} />
          Radar de Vendas
        </p>

        <div className="relative max-w-lg">
          <h2 className="text-[2.75rem] leading-[1.08] font-extrabold">
            Cada conversa da sua equipe, lida com atenção de auditor.
          </h2>
          <figure className="mt-9 max-w-md">
            <div className="papel-conversa space-y-2 rounded-xl p-4 text-[0.95rem] leading-relaxed text-tinta shadow-2xl">
              <p className="w-fit max-w-[85%] rounded-[var(--radius-bolha)] rounded-tl-sm bg-bolha-cliente px-3 py-1.5">
                Consigo ser contemplado logo no começo?
              </p>
              <p className="ml-auto w-fit max-w-[88%] rounded-[var(--radius-bolha)] rounded-tr-sm bg-bolha-vendedor px-3 py-1.5">
                <HighlightedText
                  text={SAMPLE}
                  pii={[{ type: "CPF", start: SAMPLE.indexOf("[CPF]"), end: SAMPLE.indexOf("[CPF]") + 5 }]}
                  evidence={[
                    {
                      start: SAMPLE.indexOf("sua contemplação"),
                      end: SAMPLE.indexOf(" no terceiro"),
                      severity: "critico",
                      alertId: "exemplo",
                    },
                  ]}
                />
              </p>
              <div className="rounded-lg border-l-4 border-critico bg-folha px-3 py-2 text-sm">
                <p className="flex items-center gap-2 font-bold">
                  <SeverityTag severity="critico" /> Promessa indevida
                </p>
                <p className="mt-1 text-tinta-suave">
                  Contemplação só acontece por sorteio ou lance. Ninguém pode garantir quando.
                </p>
              </div>
            </div>
            <figcaption className="mt-4 text-sm leading-relaxed text-nevoa">
              O trecho exato vira evidência, com o motivo ao lado. O CPF chega ao painel já
              mascarado, antes de qualquer análise.
            </figcaption>
          </figure>
        </div>

        <p className="relative text-sm text-nevoa">
          Código aberto, em português, com a LGPD em primeiro lugar.
        </p>
      </section>
      <section className="flex flex-col items-center justify-center gap-8 p-6">
        <p className="flex items-center gap-2.5 font-display text-lg font-bold lg:hidden">
          <RadarMark size={30} />
          Radar de Vendas
        </p>
        <LoginForm />
      </section>
    </main>
  );
}
