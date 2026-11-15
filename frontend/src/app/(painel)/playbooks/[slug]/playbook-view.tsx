"use client";

import { ChevronLeft, FlaskConical } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Button, ErrorNote, Loading, PageTitle, Panel, SeverityTag } from "@/components/ui";
import { api, type Schemas, unwrap } from "@/lib/api/client";
import { can, useMe, usePlaybook } from "@/lib/api/hooks";
import { typeLabel } from "@/lib/format";

type TestResult = Schemas["PlaybookTestOut"];

function parseLines(text: string): Schemas["PlaybookTestMessage"][] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = /^(vendedor|cliente)\s*:\s*(.*)$/i.exec(line);
      return match
        ? { sender: match[1].toLowerCase() as "vendedor" | "cliente", text: match[2] }
        : { sender: "vendedor" as const, text: line };
    });
}

export function PlaybookView() {
  const { slug } = useParams<{ slug: string }>();
  const { data, error, mutate } = usePlaybook(slug);
  const [saved, setSaved] = useState<string | null>(null);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  // A chave recria o editor quando o playbook salvo muda (nova versão).
  return (
    <PlaybookEditor
      key={`${data.origin}:${data.version}`}
      slug={slug}
      data={data}
      savedNotice={saved}
      onSaved={(playbook) => {
        setSaved(`Playbook salvo como versão ${playbook.version} da empresa.`);
        void mutate(playbook, { revalidate: false });
      }}
    />
  );
}

function PlaybookEditor({
  slug,
  data,
  savedNotice,
  onSaved,
}: {
  slug: string;
  data: Schemas["PlaybookDetail"];
  savedNotice: string | null;
  onSaved: (saved: Schemas["PlaybookDetail"]) => void;
}) {
  const { data: me } = useMe();
  const [yaml, setYaml] = useState(data.yaml);
  const [messages, setMessages] = useState(
    "cliente: É garantido que eu sou contemplado?\nvendedor: Pode ficar tranquilo, contemplação garantida!\nvendedor: Não posso garantir, é por sorteio ou lance.",
  );
  const [result, setResult] = useState<TestResult | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "erro"; text: string } | null>(
    savedNotice ? { kind: "ok", text: savedNotice } : null,
  );
  const [pending, setPending] = useState(false);
  const editable = can(me, "playbooks");

  async function test() {
    setPending(true);
    setMessage(null);
    try {
      setResult(
        await unwrap(
          api.POST("/api/v1/playbooks/{slug}/test", {
            params: { path: { slug } },
            body: { yaml: yaml !== data.yaml ? yaml : null, messages: parseLines(messages) },
          }),
        ),
      );
    } catch (exc) {
      setMessage({ kind: "erro", text: exc instanceof Error ? exc.message : "O teste falhou." });
    } finally {
      setPending(false);
    }
  }

  async function save() {
    setPending(true);
    setMessage(null);
    try {
      const saved = await unwrap(api.PUT("/api/v1/playbooks/{slug}", { params: { path: { slug } }, body: { yaml } }));
      onSaved(saved);
    } catch (exc) {
      setMessage({ kind: "erro", text: exc instanceof Error ? exc.message : "Não foi possível salvar." });
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <Link href="/playbooks" className="mb-2 inline-flex items-center gap-1 text-sm text-grafite hover:text-tinta">
        <ChevronLeft aria-hidden size={15} /> Playbooks
      </Link>
      <PageTitle title={data.name}>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
            data.origin === "empresa" ? "bg-ok-marca text-ok" : "bg-linha/70 text-grafite"
          }`}
        >
          {data.origin === "empresa" ? `Versão ${data.version} da empresa` : "Padrão do Radar"}
        </span>
      </PageTitle>
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Panel aria-labelledby="yaml" className="p-5">
          <h2 id="yaml" className="mb-3 text-lg font-bold">
            Regras em YAML
          </h2>
          <textarea
            value={yaml}
            onChange={(event) => setYaml(event.target.value)}
            readOnly={!editable}
            spellCheck={false}
            wrap="off"
            aria-label="Conteúdo do playbook em YAML"
            className="sobre-noite h-[32rem] w-full rounded-lg border border-noite-linha bg-noite p-4 font-[ui-monospace,Consolas,monospace] text-[0.8rem] leading-relaxed text-[#dfe6f5] [color-scheme:dark] focus-visible:outline-2 focus-visible:outline-sinal-forte"
          />
          {editable ? (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <Button variant="primary" onClick={save} disabled={pending || yaml === data.yaml}>
                {data.origin === "empresa" ? "Salvar nova versão" : "Salvar como playbook da empresa"}
              </Button>
              <a
                href="https://github.com/Tavares03/radar-vendas/blob/main/docs/PLAYBOOKS.md"
                className="text-sm font-medium underline underline-offset-2"
                target="_blank"
                rel="noreferrer"
              >
                Como escrever um playbook
              </a>
            </div>
          ) : (
            <p className="mt-2 text-sm text-grafite">Só a gestão pode editar playbooks.</p>
          )}
          {message ? (
            <p
              role={message.kind === "erro" ? "alert" : "status"}
              className={`mt-3 text-sm font-medium ${message.kind === "erro" ? "text-critico" : "text-ok"}`}
            >
              {message.text}
            </p>
          ) : null}
        </Panel>
        <Panel aria-labelledby="testar" className="p-5">
          <h2 id="testar" className="mb-2 text-lg font-bold">
            Testar com mensagens
          </h2>
          <p className="mb-3 text-sm text-grafite">
            Uma mensagem por linha, começando por <strong>vendedor:</strong> ou <strong>cliente:</strong>. O
            teste usa o texto do editor, mesmo antes de salvar.
          </p>
          <textarea
            value={messages}
            onChange={(event) => setMessages(event.target.value)}
            aria-label="Mensagens de teste"
            className="h-40 w-full rounded-lg border border-linha-forte bg-folha p-3 text-sm leading-relaxed"
          />
          <Button className="mt-2" onClick={test} disabled={pending}>
            <FlaskConical aria-hidden size={16} /> Testar regras
          </Button>
          {result ? (
            <div className="mt-4 space-y-3" aria-live="polite">
              {result.hits.length === 0 ? (
                <p className="rounded-lg bg-ok-marca/50 px-3 py-2 text-sm">Nenhuma regra disparou.</p>
              ) : (
                <ul className="space-y-2">
                  {result.hits.map((hit, index) => (
                    <li key={index} className="rounded-lg border border-linha px-3 py-2.5 text-sm">
                      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        {hit.severity ? (
                          <SeverityTag severity={hit.severity} />
                        ) : (
                          <span className="rounded-full bg-linha/70 px-2 py-0.5 text-xs font-bold text-grafite">
                            sinal do cliente
                          </span>
                        )}
                        <span className="font-bold">{typeLabel(hit.type)}</span>
                        <span className="ml-auto text-xs text-grafite">linha {hit.message_index + 1}</span>
                      </p>
                      <p className="mt-1.5 text-tinta-suave">
                        Trecho:{" "}
                        <mark className="evidencia" data-severity={hit.severity ?? "info"}>
                          {hit.evidence}
                        </mark>
                      </p>
                    </li>
                  ))}
                </ul>
              )}
              {Object.keys(result.disclosures).length ? (
                <p className="text-sm text-grafite">
                  Informações obrigatórias encontradas:{" "}
                  {Object.entries(result.disclosures).filter(([, index]) => index !== null).length} de{" "}
                  {Object.keys(result.disclosures).length}.
                </p>
              ) : null}
            </div>
          ) : null}
        </Panel>
      </div>
    </>
  );
}
