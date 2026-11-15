"use client";

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { ErrorNote, Loading, PageTitle } from "@/components/ui";
import { usePlaybooks } from "@/lib/api/hooks";

export function PlaybooksView() {
  const { data, error } = usePlaybooks();
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  return (
    <>
      <PageTitle
        title="Playbooks"
        lead="Um playbook diz o que é risco e o que é bom atendimento no seu setor: frases proibidas, informações obrigatórias e o peso de cada critério da nota. Para adaptar um padrão, abra-o e salve uma versão da empresa."
      />
      <ul className="grid gap-4 sm:grid-cols-2">
        {data.map((playbook) => (
          <li key={playbook.slug}>
            <Link
              href={`/playbooks/${playbook.slug}`}
              className="group flex h-full flex-col rounded-xl border border-linha bg-folha p-5 shadow-folha transition-colors hover:border-linha-forte"
            >
              <span className="flex items-start justify-between gap-3">
                <span className="font-display text-xl font-bold">{playbook.name}</span>
                <ArrowUpRight
                  aria-hidden
                  size={18}
                  className="mt-1 shrink-0 text-grafite transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-tinta"
                />
              </span>
              {playbook.description ? (
                <span className="mt-1.5 text-sm leading-relaxed text-tinta-suave">{playbook.description}</span>
              ) : null}
              <span className="mt-auto pt-4">
                <span
                  className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                    playbook.origin === "empresa" ? "bg-ok-marca text-ok" : "bg-papel text-grafite"
                  }`}
                >
                  {playbook.origin === "empresa" ? `da empresa, versão ${playbook.version}` : "padrão do Radar"}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
