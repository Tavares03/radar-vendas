"use client";

import { Upload } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { Button, Empty, ErrorNote, Loading, PageTitle, SelectField, SeverityTag } from "@/components/ui";
import { usePlaybooks, useConversations } from "@/lib/api/hooks";
import { formatDateTime, formatScore } from "@/lib/format";

const STATUS: Record<string, string> = {
  pendente: "Na fila",
  processando: "Analisando…",
  analisada: "Analisada",
  erro: "Com erro",
};
const PAGE = 30;

type ImportResult = { filename: string; status: string; error: string; duplicate?: boolean };

function ImportForm({ onDone }: { onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const playbooks = usePlaybooks();
  const [playbook, setPlaybook] = useState("");
  const [pending, setPending] = useState(false);
  const [results, setResults] = useState<ImportResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    const files = input.current?.files;
    if (!files?.length) return;
    const body = new FormData();
    for (const file of Array.from(files)) body.append("files", file);
    if (playbook) body.append("playbook", playbook);
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/imports", { method: "POST", body });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        setError(data?.error?.message ?? "O envio falhou.");
        return;
      }
      setResults(data as ImportResult[]);
      if (input.current) input.current.value = "";
      onDone();
    } catch {
      setError("O servidor não respondeu.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-labelledby="importar" className="mb-8 rounded-lg border border-linha bg-folha p-4">
      <h2 id="importar" className="font-bold">
        Importar conversas do WhatsApp
      </h2>
      <p className="mt-1 text-sm text-grafite">
        No WhatsApp: abra a conversa, toque em Mais e em Exportar conversa. Envie o .zip (com mídia,
        para transcrever os áudios) ou o .txt. Pode mandar vários de uma vez.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm text-grafite">
          Arquivos
          <input
            ref={input}
            type="file"
            multiple
            accept=".zip,.txt"
            className="text-sm text-tinta file:mr-3 file:rounded-md file:border file:border-linha-forte file:bg-papel file:px-3 file:py-1.5"
          />
        </label>
        <SelectField label="Playbook" value={playbook} onChange={(e) => setPlaybook(e.target.value)}>
          <option value="">O padrão da empresa</option>
          {playbooks.data?.map((p) => (
            <option key={p.slug} value={p.slug}>
              {p.name}
            </option>
          ))}
        </SelectField>
        <Button variant="primary" onClick={send} disabled={pending}>
          <Upload aria-hidden size={16} /> {pending ? "Enviando…" : "Enviar"}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-critico">
          {error}
        </p>
      ) : null}
      {results.length ? (
        <ul className="mt-3 space-y-1 text-sm" aria-live="polite">
          {results.map((item, index) => (
            <li key={index}>
              <strong>{item.filename}</strong>:{" "}
              {item.duplicate
                ? "já tinha sido importado; nada mudou."
                : item.status === "falhou"
                  ? item.error
                  : "recebido, a análise começa em seguida."}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function ConversationsView() {
  const [limit, setLimit] = useState(PAGE);
  const { data, error, mutate } = useConversations({ limit });

  return (
    <>
      <PageTitle title="Conversas" />
      <ImportForm onDone={() => void mutate()} />
      {error ? <ErrorNote error={error} /> : null}
      {!data && !error ? <Loading /> : null}
      {data && data.items.length === 0 ? (
        <Empty title="Nenhuma conversa ainda">Importe um export do WhatsApp acima para começar.</Empty>
      ) : null}
      {data && data.items.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[44rem] text-left text-sm">
            <thead className="border-b border-linha-forte text-grafite">
              <tr>
                <th className="py-2 font-medium">Cliente</th>
                <th className="py-2 font-medium">Vendedor</th>
                <th className="py-2 font-medium">Última mensagem</th>
                <th className="py-2 text-right font-medium">Mensagens</th>
                <th className="py-2 text-right font-medium">Nota</th>
                <th className="py-2 pl-4 font-medium">Risco</th>
                <th className="py-2 font-medium">Situação</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-linha">
              {data.items.map((conversation) => (
                <tr key={conversation.id} className="hover:bg-folha">
                  <td className="py-2.5">
                    <Link href={`/conversas/${conversation.id}`} className="font-semibold hover:underline">
                      {conversation.customer_label}
                    </Link>
                    {conversation.role_confidence !== "alta" ? (
                      <span className="ml-2 text-xs text-atencao">confirmar vendedor</span>
                    ) : null}
                  </td>
                  <td className="py-2.5">{conversation.seller?.display_name ?? "—"}</td>
                  <td className="py-2.5 text-grafite">
                    {conversation.last_message_at ? formatDateTime(conversation.last_message_at) : "—"}
                  </td>
                  <td className="numeros py-2.5 text-right">{conversation.message_count}</td>
                  <td className="numeros py-2.5 text-right font-semibold">{formatScore(conversation.score)}</td>
                  <td className="py-2.5 pl-4">
                    {conversation.max_severity ? <SeverityTag severity={conversation.max_severity} /> : <span className="text-grafite">—</span>}
                  </td>
                  <td className={`py-2.5 ${conversation.status === "erro" ? "text-critico" : "text-grafite"}`}>
                    {STATUS[conversation.status] ?? conversation.status}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.total > data.items.length ? (
            <div className="mt-4 text-center">
              <Button onClick={() => setLimit((current) => current + PAGE)}>Carregar mais</Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
