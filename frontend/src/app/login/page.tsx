import type { Metadata } from "next";

import { HighlightedText } from "@/components/highlighted-text";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Entrar" };

const SAMPLE = "Fica tranquilo, sua contemplação é garantida no terceiro mês. Me passa seu CPF [CPF]?";

export default function LoginPage() {
  return (
    <main className="grid min-h-screen md:grid-cols-[1fr_minmax(22rem,30rem)]">
      <section
        aria-label="O que o Radar faz"
        className="hidden flex-col justify-center gap-6 bg-tinta px-12 text-papel md:flex"
      >
        <p className="max-w-md text-[2.1rem] leading-tight font-extrabold tracking-tight">
          Cada conversa da sua equipe, lida com atenção de auditor.
        </p>
        <figure className="max-w-md">
          <div className="rounded-[var(--radius-bolha)] rounded-br-sm bg-bolha-vendedor px-4 py-3 text-tinta">
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
          </div>
          <figcaption className="mt-3 text-sm text-papel/80">
            Promessa de contemplação marcada como risco crítico, com o trecho exato. O CPF chega ao
            painel já mascarado.
          </figcaption>
        </figure>
      </section>
      <section className="flex items-center justify-center p-6">
        <LoginForm />
      </section>
    </main>
  );
}
