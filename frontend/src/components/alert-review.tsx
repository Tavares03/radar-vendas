"use client";

import { useState } from "react";

import { api, type Schemas, unwrap } from "@/lib/api/client";
import { statusLabel } from "@/lib/format";

import { Button } from "./ui";

type Alert = Schemas["AlertOut"];
type Assignee = Schemas["AssigneeOut"];
type Status = Schemas["AlertStatus"];

const ACTIONS: { status: Status; label: string; variant: "primary" | "secondary" | "danger" }[] = [
  { status: "confirmado", label: "Confirmar", variant: "danger" },
  { status: "falso_positivo", label: "Falso positivo", variant: "secondary" },
  { status: "resolvido", label: "Resolvido", variant: "secondary" },
];

/** Revisão de um alerta: status, responsável e nota. Cada mudança fica na auditoria. */
export function AlertReview({
  alert,
  users,
  onSaved,
}: {
  alert: Alert;
  users: Assignee[];
  onSaved: (alert: Alert) => void;
}) {
  const [note, setNote] = useState(alert.review_note);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function save(body: Schemas["AlertUpdate"]) {
    setPending(true);
    setError(null);
    try {
      const updated = await unwrap(
        api.PATCH("/api/v1/alerts/{alert_id}", { params: { path: { alert_id: alert.id } }, body }),
      );
      onSaved(updated);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Não foi possível salvar.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-3 border-t border-linha pt-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Mudar o status do alerta">
        {ACTIONS.map((action) => (
          <Button
            key={action.status}
            variant={alert.status === action.status ? "primary" : action.variant}
            disabled={pending || alert.status === action.status}
            aria-pressed={alert.status === action.status}
            onClick={() => save({ status: action.status })}
          >
            {action.label}
          </Button>
        ))}
        {alert.status !== "aberto" ? (
          <Button variant="quiet" disabled={pending} onClick={() => save({ status: "aberto" })}>
            Reabrir
          </Button>
        ) : null}
      </div>
      <label className="flex flex-col gap-1 text-sm text-grafite">
        Responsável
        <select
          value={alert.assigned_to?.id ?? ""}
          disabled={pending}
          onChange={(event) =>
            save(event.target.value ? { assigned_to_user_id: event.target.value } : { unassign: true })
          }
          className="rounded-md border border-linha-forte bg-folha px-2 py-1.5 text-tinta"
        >
          <option value="">Ninguém</option>
          {users.map((user) => (
            <option key={user.id} value={user.id}>
              {user.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-sm text-grafite">
        Nota da revisão
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={2}
          maxLength={2000}
          className="rounded-md border border-linha-forte bg-folha px-2 py-1.5 text-tinta"
          placeholder="O que foi verificado, combinado com o vendedor…"
        />
      </label>
      <div className="flex items-center gap-3">
        <Button disabled={pending || note === alert.review_note} onClick={() => save({ note })}>
          Salvar nota
        </Button>
        <span className="text-xs text-grafite">Status atual: {statusLabel(alert.status)}</span>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-critico">
          {error}
        </p>
      ) : null}
    </div>
  );
}
