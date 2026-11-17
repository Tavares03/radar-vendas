"use client";

import { Hourglass, Trash2 } from "lucide-react";
import { useState } from "react";

import { api, type Schemas, unwrap } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";

import { Button, FIELD } from "./ui";

type Removal = Schemas["RemovalRequestOut"];

/**
 * Remoção de conversa com aprovação: o vendedor só pede (com motivo) e a gestão decide. Se o
 * vendedor apagasse sozinho, poderia esconder justamente as conversas ruins.
 */
export function RemovalRequestBox({
  conversationId,
  live,
  pending,
  canRequest,
  canDecide,
  onChanged,
  onRemoved,
}: {
  conversationId: string;
  /** Conversa do WhatsApp conectado: dá para parar de capturar o contato. */
  live: boolean;
  pending: Removal | null | undefined;
  canRequest: boolean;
  canDecide: boolean;
  onChanged: () => void;
  onRemoved: () => void;
}) {
  const [writing, setWriting] = useState(false);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [stopCapturing, setStopCapturing] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>, after: () => void) {
    setBusy(true);
    setError(null);
    try {
      await action();
      after();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Não foi possível concluir.");
    } finally {
      setBusy(false);
    }
  }

  function request() {
    void run(
      () =>
        unwrap(
          api.POST("/api/v1/conversations/{conversation_id}/removal-request", {
            params: { path: { conversation_id: conversationId } },
            body: { reason: reason.trim() },
          }),
        ),
      () => {
        setWriting(false);
        setReason("");
        onChanged();
      },
    );
  }

  function decide(approve: boolean) {
    if (!pending) return;
    if (
      approve &&
      !window.confirm("Aprovar apaga a conversa, as mensagens, os áudios e a análise. Não há como desfazer.")
    ) {
      return;
    }
    const path = approve
      ? "/api/v1/removal-requests/{request_id}/approve"
      : "/api/v1/removal-requests/{request_id}/reject";
    void run(
      () =>
        unwrap(
          api.POST(path, {
            params: { path: { request_id: pending.id } },
            body: { note: note.trim(), stop_capturing: live && stopCapturing },
          }),
        ),
      approve ? onRemoved : onChanged,
    );
  }

  const errorNote = error ? (
    <p role="alert" className="mt-2 text-sm font-medium text-critico">
      {error}
    </p>
  ) : null;

  if (pending) {
    return (
      <section
        aria-label="Pedido de remoção"
        className="mt-3 rounded-lg border border-atencao-forte/40 bg-atencao-marca/40 px-4 py-3 text-sm"
      >
        <p className="flex items-start gap-2">
          <Hourglass aria-hidden size={16} className="mt-0.5 shrink-0 text-atencao" />
          <span>
            <strong>Remoção pedida</strong>
            {pending.requested_by ? ` por ${pending.requested_by}` : ""} em {formatDateTime(pending.created_at)}:
            {" “"}
            {pending.reason}
            {"”. "}
            {canDecide
              ? "A conversa continua no Radar até você decidir."
              : "A conversa continua no Radar até a gestão decidir."}
          </span>
        </p>
        {canDecide ? (
          <div className="mt-3 space-y-2">
            <label className="flex max-w-lg flex-col gap-1 text-[0.8rem] font-medium text-grafite">
              Nota para o vendedor (opcional)
              <input
                value={note}
                onChange={(event) => setNote(event.target.value)}
                maxLength={1000}
                className={FIELD}
              />
            </label>
            {live ? (
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={stopCapturing}
                  onChange={(event) => setStopCapturing(event.target.checked)}
                />
                Ao aprovar, parar de capturar as mensagens deste contato
              </label>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button variant="danger" disabled={busy} onClick={() => decide(true)}>
                <Trash2 aria-hidden size={15} /> Aprovar e apagar
              </Button>
              <Button disabled={busy} onClick={() => decide(false)}>
                Recusar (a conversa fica)
              </Button>
            </div>
          </div>
        ) : null}
        {errorNote}
      </section>
    );
  }

  // Quem pode apagar direto não precisa pedir; quem só lê não pede.
  if (!canRequest || canDecide) return null;

  return (
    <section aria-label="Pedir remoção" className="mt-3">
      {writing ? (
        <div className="rounded-lg border border-linha bg-folha px-4 py-3">
          <label className="flex flex-col gap-1 text-sm font-medium">
            Por que esta conversa deveria sair do Radar?
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={2}
              maxLength={1000}
              placeholder="Ex.: é uma conversa pessoal, com um familiar."
              className={`${FIELD} font-normal`}
            />
          </label>
          <p className="mt-1 text-xs text-grafite">
            A gestão recebe o pedido e decide. Enquanto isso, a conversa continua no Radar.
          </p>
          <div className="mt-2 flex gap-2">
            <Button variant="primary" disabled={busy || reason.trim().length < 5} onClick={request}>
              Enviar pedido
            </Button>
            <Button variant="quiet" disabled={busy} onClick={() => setWriting(false)}>
              Cancelar
            </Button>
          </div>
          {errorNote}
        </div>
      ) : (
        <Button variant="quiet" onClick={() => setWriting(true)}>
          <Trash2 aria-hidden size={15} /> Pedir remoção desta conversa
        </Button>
      )}
    </section>
  );
}
