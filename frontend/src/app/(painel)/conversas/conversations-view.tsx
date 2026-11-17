"use client";

import { FileArchive, Hourglass, Upload, X } from "lucide-react";
import Link from "next/link";
import { type DragEvent, useRef, useState } from "react";

import {
  Button,
  Empty,
  ErrorNote,
  Loading,
  PageTitle,
  Panel,
  ScoreBadge,
  SelectField,
  SeverityTag,
} from "@/components/ui";
import { can, useConversations, useMe, usePlaybooks, useRemovalRequests } from "@/lib/api/hooks";
import { formatDateTime, plural } from "@/lib/format";

const STATUS: Record<string, string> = {
  aguardando: "Em andamento",
  pendente: "Na fila",
  processando: "Analisando…",
  analisada: "Analisada",
  erro: "Com erro",
};
const PAGE = 30;
const ACCEPTED = /\.(zip|txt)$/i;

type ImportResult = { filename: string; status: string; error: string; duplicate?: boolean };

function ImportForm({ onDone }: { onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const playbooks = usePlaybooks();
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [playbook, setPlaybook] = useState("");
  const [pending, setPending] = useState(false);
  const [results, setResults] = useState<ImportResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  function add(list: FileList | null) {
    if (!list?.length) return;
    const incoming = Array.from(list);
    const valid = incoming.filter((file) => ACCEPTED.test(file.name));
    setError(valid.length < incoming.length ? "Só arquivos .zip ou .txt exportados do WhatsApp." : null);
    setFiles((current) => {
      const names = new Set(current.map((f) => `${f.name}:${f.size}`));
      return [...current, ...valid.filter((f) => !names.has(`${f.name}:${f.size}`))];
    });
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    add(event.dataTransfer.files);
  }

  async function send() {
    if (!files.length) return;
    const body = new FormData();
    for (const file of files) body.append("files", file);
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
      setFiles([]);
      if (input.current) input.current.value = "";
      onDone();
    } catch {
      setError("O servidor não respondeu.");
    } finally {
      setPending(false);
    }
  }

  return (
    <Panel aria-labelledby="importar" className="mb-8 p-5">
      <h2 id="importar" className="text-lg font-bold">
        Importar conversas do WhatsApp
      </h2>
      <p className="mt-1 max-w-3xl text-sm text-grafite">
        No WhatsApp, abra a conversa, toque em Mais e em Exportar conversa. Envie o .zip (com mídia,
        para transcrever os áudios) ou o .txt. Pode mandar vários de uma vez.
      </p>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`mt-4 rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors ${
          dragging ? "border-sinal-forte bg-ok-marca/40" : "border-linha-forte bg-papel/50"
        }`}
      >
        <FileArchive aria-hidden size={26} strokeWidth={1.6} className="mx-auto text-grafite" />
        <p className="mt-2 text-sm">
          Arraste os arquivos para cá ou{" "}
          <label className="cursor-pointer font-semibold underline underline-offset-2 focus-within:outline-2 focus-within:outline-offset-2">
            escolha no computador
            <input
              ref={input}
              type="file"
              multiple
              accept=".zip,.txt"
              aria-label="Arquivos"
              className="sr-only"
              onChange={(event) => add(event.target.files)}
            />
          </label>
        </p>
        <p className="mt-1 text-xs text-grafite">Os dados pessoais são mascarados antes de qualquer análise.</p>
      </div>
      {files.length ? (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Arquivos escolhidos">
          {files.map((file, index) => (
            <li
              key={`${file.name}:${file.size}`}
              className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-linha bg-papel py-1 pr-1 pl-3 text-sm"
            >
              <span className="truncate">{file.name}</span>
              <button
                type="button"
                aria-label={`Tirar ${file.name}`}
                className="rounded-full p-0.5 text-grafite hover:bg-linha hover:text-tinta"
                onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}
              >
                <X aria-hidden size={14} />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <SelectField label="Playbook" value={playbook} onChange={(e) => setPlaybook(e.target.value)}>
          <option value="">O padrão da empresa</option>
          {playbooks.data?.map((p) => (
            <option key={p.slug} value={p.slug}>
              {p.name}
            </option>
          ))}
        </SelectField>
        <Button variant="primary" onClick={send} disabled={pending || files.length === 0}>
          <Upload aria-hidden size={16} />
          {pending ? "Enviando…" : files.length > 1 ? `Enviar ${files.length} arquivos` : "Enviar"}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm font-medium text-critico">
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
    </Panel>
  );
}

/** Pedidos de remoção esperando a gestão: a decisão é tomada dentro de cada conversa. */
function PendingRemovals() {
  const { data } = useRemovalRequests(true);
  if (!data || data.length === 0) return null;
  return (
    <Panel aria-labelledby="pedidos-de-remocao" className="mb-6 border-l-4 border-l-atencao-forte p-5">
      <h2 id="pedidos-de-remocao" className="flex items-center gap-2 font-bold">
        <Hourglass aria-hidden size={17} className="text-atencao" />
        {data.length === 1 ? "1 pedido de remoção esperando você" : `${data.length} pedidos de remoção esperando você`}
      </h2>
      <ul className="mt-2 divide-y divide-linha text-sm">
        {data.map((request) => (
          <li key={request.id} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
            <span>
              <strong>{request.requested_by || "Alguém"}</strong> pediu para tirar{" "}
              {request.conversation_label}: “{request.reason}”
            </span>
            {request.conversation_id ? (
              <Link href={`/conversas/${request.conversation_id}`} className="font-semibold underline underline-offset-2">
                Abrir e decidir
              </Link>
            ) : null}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function ConversationsView() {
  const [limit, setLimit] = useState(PAGE);
  const { data: me } = useMe();
  const { data, error, mutate } = useConversations({ limit });
  // Quem só lê (auditoria) não vê o envio: a API recusaria de qualquer jeito.
  const canImport = can(me, "importar");

  return (
    <>
      <PageTitle title="Conversas" />
      {can(me, "excluir") ? <PendingRemovals /> : null}
      {canImport ? <ImportForm onDone={() => void mutate()} /> : null}
      {error ? <ErrorNote error={error} /> : null}
      {!data && !error ? <Loading /> : null}
      {data && data.items.length === 0 ? (
        <Empty title="Nenhuma conversa ainda">
          {canImport
            ? "Importe um export do WhatsApp acima para começar."
            : "As conversas aparecem aqui quando a equipe importar os exports do WhatsApp."}
        </Empty>
      ) : null}
      {data && data.items.length > 0 ? (
        <>
          <p className="mb-3 text-sm text-grafite">
            {plural(data.total, "conversa", "conversas")}, as mais recentes primeiro.
          </p>
          <Panel className="overflow-x-auto">
            <table className="w-full min-w-[46rem] text-left text-sm">
              <thead className="border-b border-linha text-xs text-grafite">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Cliente</th>
                  <th className="px-4 py-2.5 font-medium">Vendedor</th>
                  <th className="px-4 py-2.5 font-medium">Última mensagem</th>
                  <th className="px-4 py-2.5 text-right font-medium">Mensagens</th>
                  <th className="px-4 py-2.5 font-medium">Risco</th>
                  <th className="px-4 py-2.5 text-right font-medium">Nota</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-linha">
                {data.items.map((conversation) => (
                  <tr key={conversation.id} className="hover:bg-papel/60">
                    <td className="px-4 py-2.5">
                      <Link href={`/conversas/${conversation.id}`} className="font-semibold hover:underline">
                        {conversation.customer_label}
                      </Link>
                      {conversation.source === "evolution" ? (
                        <span
                          className="ml-2 rounded-full bg-ok-marca px-2 py-0.5 text-xs font-medium text-ok"
                          title="Chegou pelo WhatsApp conectado"
                        >
                          ao vivo
                        </span>
                      ) : null}
                      {conversation.role_confidence !== "alta" ? (
                        <span className="ml-2 rounded-full bg-atencao-marca px-2 py-0.5 text-xs font-medium text-atencao">
                          confirmar vendedor
                        </span>
                      ) : null}
                    </td>
                    <td className="px-4 py-2.5">{conversation.seller?.display_name ?? "—"}</td>
                    <td className="numeros px-4 py-2.5 text-grafite">
                      {conversation.last_message_at ? formatDateTime(conversation.last_message_at) : "—"}
                    </td>
                    <td className="numeros px-4 py-2.5 text-right">{conversation.message_count}</td>
                    <td className="px-4 py-2.5">
                      {conversation.status !== "analisada" ? (
                        <span className={conversation.status === "erro" ? "font-medium text-critico" : "text-grafite"}>
                          {STATUS[conversation.status] ?? conversation.status}
                        </span>
                      ) : conversation.max_severity ? (
                        <SeverityTag severity={conversation.max_severity} />
                      ) : (
                        <span className="text-grafite">Sem alertas</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <ScoreBadge score={conversation.score} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
          {data.total > data.items.length ? (
            <div className="mt-5 text-center">
              <Button onClick={() => setLimit((current) => current + PAGE)}>Carregar mais</Button>
            </div>
          ) : null}
        </>
      ) : null}
    </>
  );
}
