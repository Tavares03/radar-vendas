"use client";

import { Eye, EyeOff, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { AlertReview } from "@/components/alert-review";
import { MessageBubble } from "@/components/message-bubble";
import { ScorePanel } from "@/components/score-panel";
import { Button, ErrorNote, Loading, SeverityTag, StatusTag } from "@/components/ui";
import { api, type Schemas, unwrap } from "@/lib/api/client";
import { can, useAnalysis, useConversation, useMe, useAssignees } from "@/lib/api/hooks";
import { formatDay, sentimentLabel, stageLabel } from "@/lib/format";
import { type EvidenceRange, findEvidence, type Severity } from "@/lib/highlight";

type Alert = Schemas["AlertOut"];

const LAYERS: Record<string, string> = {
  regra: "regras do playbook",
  classificador: "classificador próprio",
  metrica: "métricas de tempo",
  llm: "LLM",
};

function dayKey(iso: string) {
  return new Date(iso).toDateString();
}

function scrollToMessage(id: string | null | undefined) {
  if (!id) return;
  document.getElementById(`m-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function subscribeToHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

/** Mensagem apontada pela âncora da URL (`#m-<id>`), vinda de um alerta. */
function useHashMessage(): string | null {
  const hash = useSyncExternalStore(
    subscribeToHash,
    () => window.location.hash,
    () => "",
  );
  return hash.startsWith("#m-") ? hash.slice(3) : null;
}

export function ConversationView() {
  const { id } = useParams<{ id: string }>();
  const { data: me } = useMe();
  const [reveal, setReveal] = useState(false);
  const [clicked, setClicked] = useState<string | null>(null);
  const [reprocessing, setReprocessing] = useState(false);
  const conversation = useConversation(id, reveal);
  const analysis = useAnalysis(id);
  const users = useAssignees(can(me, "revisar"));
  const fromHash = useHashMessage();
  const selected = clicked ?? fromHash;
  const loaded = Boolean(conversation.data);

  useEffect(() => {
    // Só sincroniza o DOM (rolagem) quando a conversa aparece com uma âncora na URL.
    if (loaded && fromHash) requestAnimationFrame(() => scrollToMessage(fromHash));
  }, [loaded, fromHash]);

  const alerts = useMemo(() => analysis.data?.alerts ?? [], [analysis.data]);
  const evidenceByMessage = useMemo(() => {
    const map = new Map<string, EvidenceRange[]>();
    const messages = conversation.data?.messages ?? [];
    for (const alert of alerts) {
      if (!alert.message_id || alert.category !== "risco" || alert.status === "falso_positivo") continue;
      const message = messages.find((m) => m.id === alert.message_id);
      if (!message) continue;
      const found = findEvidence(message.text, alert.evidence);
      if (!found) continue;
      const list = map.get(message.id) ?? [];
      list.push({ ...found, severity: alert.severity as Severity, alertId: alert.id });
      map.set(message.id, list);
    }
    return map;
  }, [alerts, conversation.data]);

  async function reprocess() {
    setReprocessing(true);
    try {
      await unwrap(
        api.POST("/api/v1/conversations/{conversation_id}/reprocess", {
          params: { path: { conversation_id: id } },
        }),
      );
      await Promise.all([conversation.mutate(), analysis.mutate()]);
    } finally {
      setReprocessing(false);
    }
  }

  function toggleReveal() {
    if (reveal) {
      setReveal(false);
      return;
    }
    const ok = window.confirm(
      "Mostrar o texto original, sem máscara? Este acesso fica registrado na trilha de auditoria.",
    );
    if (ok) setReveal(true);
  }

  if (conversation.error) return <ErrorNote error={conversation.error} />;
  const data = conversation.data;
  if (!data) return <Loading />;
  const result = analysis.data;

  return (
    <>
      <header className="mb-6">
        <Link href="/conversas" className="text-sm text-grafite hover:text-tinta">
          Conversas
        </Link>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[1.75rem] leading-tight font-extrabold tracking-tight">{data.customer_label}</h1>
            <p className="text-sm text-grafite">
              Com {data.seller?.display_name ?? "vendedor não identificado"}, {data.message_count} mensagens,
              playbook {data.playbook}
              {data.started_at ? `, desde ${formatDay(data.started_at)}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {can(me, "revelar") ? (
              <Button onClick={toggleReveal} aria-pressed={reveal}>
                {reveal ? <EyeOff aria-hidden size={16} /> : <Eye aria-hidden size={16} />}
                {reveal ? "Voltar ao texto mascarado" : "Mostrar texto original"}
              </Button>
            ) : null}
            <Button onClick={reprocess} disabled={reprocessing}>
              <RefreshCw aria-hidden size={16} className={reprocessing ? "animate-spin" : ""} />
              Analisar de novo
            </Button>
          </div>
        </div>
        {reveal ? (
          <p className="mt-3 border-l-4 border-tinta bg-folha px-3 py-2 text-sm">
            Você está vendo o texto original. Este acesso foi registrado na auditoria.
            {data.raw_purged ? " Parte do original já foi apagada pela política de retenção." : ""}
          </p>
        ) : null}
        {data.warnings.length ? (
          <ul className="mt-3 space-y-1 border-l-4 border-[#ffb703] bg-folha px-3 py-2 text-sm">
            {data.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        ) : null}
      </header>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <section aria-label="Mensagens" className="rounded-lg bg-transcricao px-3 py-4 sm:px-5">
          <ol className="space-y-2">
            {data.messages.map((message, index) => {
              const newDay = index === 0 || dayKey(message.sent_at) !== dayKey(data.messages[index - 1].sent_at);
              return (
                <Fragment key={message.id}>
                  {newDay ? (
                    <li className="py-2 text-center">
                      <span className="rounded-full bg-folha px-3 py-1 text-xs text-grafite">
                        {formatDay(message.sent_at)}
                      </span>
                    </li>
                  ) : null}
                  <li>
                    <MessageBubble
                      message={message}
                      evidence={evidenceByMessage.get(message.id) ?? []}
                      highlighted={selected === message.id}
                    />
                  </li>
                </Fragment>
              );
            })}
          </ol>
        </section>

        <aside aria-label="Análise" className="order-first space-y-8 lg:order-none lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto lg:pr-1">
          {!result ? (
            <p className="text-sm text-grafite">
              {data.status === "erro" ? "A análise falhou. Tente analisar de novo." : "A análise ainda não terminou."}
            </p>
          ) : (
            <>
              <ScorePanel score={result.score} criteria={result.criteria} />
              {result.summary || result.suggestion ? (
                <section className="space-y-3">
                  {result.summary ? (
                    <div>
                      <h2 className="font-bold">Resumo</h2>
                      <p className="mt-1 text-sm">{result.summary}</p>
                      <p className="mt-1 text-xs text-grafite">
                        Etapa: {stageLabel(result.stage)}. Cliente: {sentimentLabel(result.sentiment).toLowerCase()}.
                      </p>
                    </div>
                  ) : null}
                  {result.suggestion ? (
                    <div className="rounded-lg border border-linha bg-folha p-3">
                      <h2 className="text-sm font-bold">Próxima mensagem sugerida</h2>
                      <p className="mt-1 text-sm italic">“{result.suggestion}”</p>
                    </div>
                  ) : null}
                </section>
              ) : null}
              <AlertsMargin
                alerts={alerts}
                canReview={can(me, "revisar")}
                users={users.data ?? []}
                selected={selected}
                onSelect={(alert) => {
                  setClicked(alert.message_id ?? null);
                  scrollToMessage(alert.message_id);
                }}
                onSaved={() => void analysis.mutate()}
              />
              <p className="text-xs text-grafite">
                Analisada com {result.layers.map((layer) => LAYERS[layer] ?? layer).join(", ")}
                {result.llm.provider ? ` (${result.llm.provider})` : ""}.
                {result.llm.error ? ` Sem LLM nesta análise: ${result.llm.error}` : ""}
              </p>
            </>
          )}
        </aside>
      </div>
    </>
  );
}

function AlertsMargin({
  alerts,
  canReview,
  users,
  selected,
  onSelect,
  onSaved,
}: {
  alerts: Alert[];
  canReview: boolean;
  users: Schemas["AssigneeOut"][];
  selected: string | null;
  onSelect: (alert: Alert) => void;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <section aria-labelledby="alertas-da-conversa">
      <h2 id="alertas-da-conversa" className="font-bold">
        Alertas ({alerts.length})
      </h2>
      {alerts.length === 0 ? (
        <p className="mt-1 text-sm text-grafite">Nenhum risco ou oportunidade perdida encontrada.</p>
      ) : (
        <ul className="mt-2 space-y-3">
          {alerts.map((alert) => (
            <li
              key={alert.id}
              className={`border-l-2 pl-3 ${alert.message_id && alert.message_id === selected ? "border-tinta" : "border-linha"}`}
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <SeverityTag severity={alert.severity} />
                <StatusTag status={alert.status} />
              </div>
              <p className="mt-0.5 text-sm font-semibold">{alert.label}</p>
              <p className="mt-0.5 text-sm text-tinta-suave">{alert.explanation}</p>
              <div className="mt-1 flex gap-3 text-sm">
                {alert.message_id ? (
                  <button type="button" className="underline underline-offset-2" onClick={() => onSelect(alert)}>
                    Ver no texto
                  </button>
                ) : null}
                {canReview ? (
                  <button
                    type="button"
                    className="underline underline-offset-2"
                    aria-expanded={open === alert.id}
                    onClick={() => setOpen(open === alert.id ? null : alert.id)}
                  >
                    Revisar
                  </button>
                ) : null}
              </div>
              {open === alert.id ? (
                <div className="mt-2">
                  <AlertReview alert={alert} users={users} onSaved={onSaved} />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
