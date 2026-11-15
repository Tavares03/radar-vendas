"use client";

import Link from "next/link";

import { ErrorNote, Loading, PageTitle } from "@/components/ui";
import { usePlaybooks } from "@/lib/api/hooks";

export function PlaybooksView() {
  const { data, error } = usePlaybooks();
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  return (
    <>
      <PageTitle title="Playbooks" />
      <p className="mb-6 max-w-2xl text-sm text-grafite">
        Um playbook diz o que é risco e o que é bom atendimento no seu setor: frases proibidas,
        informações obrigatórias e o peso de cada critério da nota. Os padrões vêm com o Radar; para
        adaptar um, abra-o e salve uma versão da empresa.
      </p>
      <ul className="divide-y divide-linha border-y border-linha">
        {data.map((playbook) => (
          <li key={playbook.slug} className="py-3">
            <div className="flex flex-wrap items-baseline gap-x-3">
              <Link href={`/playbooks/${playbook.slug}`} className="font-semibold hover:underline">
                {playbook.name}
              </Link>
              <span className="text-sm text-grafite">
                {playbook.origin === "empresa" ? `da empresa, versão ${playbook.version}` : "padrão do Radar"}
              </span>
            </div>
            {playbook.description ? <p className="mt-1 max-w-3xl text-sm text-tinta-suave">{playbook.description}</p> : null}
          </li>
        ))}
      </ul>
    </>
  );
}
