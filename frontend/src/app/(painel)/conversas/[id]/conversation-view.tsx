"use client";

import { ChevronLeft, Eye, EyeOff, Lightbulb, RefreshCw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { AlertReview } from "@/components/alert-review";
import { MessageBubble } from "@/components/message-bubble";
import { ScorePanel } from "@/components/score-panel";
import { Button, ErrorNote, Initials, Loading, Panel, SeverityTag, StatusTag } from "@/components/ui";
import { api, type Schemas, unwrap } from "@/lib/api/client";
import { can, useAnalysis, useAssignees, useConversation, useMe, usePlaybooks } from "@/lib/api/hooks";
import { formatDay, sentimentLabel, stageLabel } from "@/lib/format";
import { type EvidenceRange, findEvidence, type Severity } from "@/lib/highlight";

type Alert = Schemas["AlertOut"];

const LAYERS: Record<string, string> = {
  regra: "regras do playbook",
  classificador: "classificador próprio",
  metrica: "métricas de tempo",
  llm: "LLM",
};

const SEVERITY_ORDER: Record<string, number> = { critico: 0, atencao: 1, info: 2 };

const STRIPE: Record<string, string> = {
  critico: "border-critico",
  atencao: "border-atencao-forte",
  info: "border-info",
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
  const [reprocessError, setReprocessError] = useState<string | null>(null);
  const conversation = useConversation(id, reveal);
  const analysis = useAnalysis(id);
  const users = useAssignees(can(me, "revisar"));
  const playbooks = usePlaybooks();
  const fromHash = useHashMessage();
  const selected = clicked ?? fromHash;
  const loaded = Boolean(conversation.data);

  useEffect(() => {
    // Só sincroniza o DOM (rolagem) quando a conversa aparece com uma âncora na URL.
    if (loaded && fromHash) requestAnimationFrame(() => scrollToMessage(fromHash));
  }, [loaded, fromHash]);

  // Os mais graves primeiro; dentro da mesma severidade, na ordem em que aparecem na conversa.
  const alerts = useMemo(
    () =>
      [...(analysis.data?.alerts ?? [])].sort(
        (a, b) =>
          (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9) ||
          (a.message_index ?? Number.MAX_SAFE_INTEGER) - (b.message_index ?? Number.MAX_SAFE_INTEGER),
      ),
    [analysis.data],
  );
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
    setReprocessError(null);
    try {
      await unwrap(
        api.POST("/api/v1/conversations/{conversation_id}/reprocess", {
          params: { path: { conversation_id: id } },
        }),
      );
      await Promise.all([conversation.mutate(), analysis.mutate()]);
    } catch (exc) {
      setReprocessError(exc instanceof Error ? exc.message : "Não foi possível analisar de novo.");
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
  const sellerName = data.seller?.display_name ?? "vendedor não identificado";
  const playbookName = playbooks.data?.find((p) => p.slug === data.playbook)?.name ?? data.playbook;

  return (
    <>
      <header className="mb-6">
        <Link href="/conversas" className="inline-flex items-center gap-1 text-sm text-grafite hover:text-tinta">
          <ChevronLeft aria-hidden size={15} /> Conversas
        </Link>
        <div className="mt-1.5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[2rem] leading-[1.1] font-extrabold">{data.customer_label}</h1>
            <p className="mt-1.5 text-sm text-grafite">
              Com {sellerName}, {data.message_count} mensagens, playbook {playbookName}
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
            {can(me, "importar") ? (
              <Button onClick={reprocess} disabled={reprocessing}>
                <RefreshCw aria-hidden size={16} className={reprocessing ? "animate-spin" : ""} />
                {reprocessing ? "Analisando…" : "Analisar de novo"}
              </Button>
            ) : null}
          </div>
        </div>
        {reprocessError ? (
          <p role="alert" className="mt-3 text-sm font-medium text-critico">
            {reprocessError}
          </p>
        ) : null}
        {reveal ? (
          <p className="mt-3 flex items-start gap-2 rounded-lg border border-tinta/20 bg-folha px-3 py-2 text-sm">
            <Eye aria-hidden size={16} className="mt-0.5 shrink-0" />
            <span>
              Você está vendo o texto original. Este acesso foi registrado na auditoria.
              {data.raw_purged ? " Parte do original já foi apagada pela política de retenção." : ""}
            </span>
          </p>
        ) : null}
        {data.warnings.length ? (
          <ul className="mt-3 space-y-1 rounded-lg border border-atencao-forte/40 bg-atencao-marca/40 px-3 py-2 text-sm">
            {data.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        ) : null}
      </header>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_23rem]">
        <section aria-label="Mensagens" className="overflow-hidden rounded-xl border border-linha shadow-folha">
          <div className="sobre-noite flex items-center gap-3 bg-noite px-4 py-3 text-white">
            <Initials name={data.customer_label} className="bg-noite-suave text-white" />
            <div className="min-w-0">
              <p className="truncate leading-tight font-semibold">{data.customer_label}</p>
              <p className="truncate text-xs text-nevoa">atendimento de {sellerName}</p>
            </div>
            <span className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-full bg-noite-suave px-2.5 py-1 text-xs text-nevoa">
              <ShieldCheck aria-hidden size={14} className="text-sinal" />
              {reveal ? "texto original" : "dados mascarados"}
            </span>
          </div>
          <ol className="papel-conversa space-y-1.5 px-3 py-4 sm:px-6">
            {data.messages.map((message, index) => {
              const previous = index > 0 ? data.messages[index - 1] : null;
              const newDay = !previous || dayKey(message.sent_at) !== dayKey(previous.sent_at);
              const turn = !newDay && previous?.sender_role !== message.sender_role;
              return (
                <Fragment key={message.id}>
                  {newDay ? (
                    <li className="py-2 text-center">
                      <span className="rounded-md bg-folha/90 px-3 py-1 text-xs font-medium text-grafite shadow-[0_1px_0.5px_rgb(15_26_51/0.12)]">
                        {formatDay(message.sent_at)}
                      </span>
                    </li>
                  ) : null}
                  <li className={turn ? "pt-2" : ""}>
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

        <aside
          aria-label="Análise"
          className="order-first space-y-4 lg:order-none lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto lg:pr-1 lg:pb-1 lg:[scrollbar-width:thin]"
        >
          {!result ? (
            <Panel className="p-5 text-sm text-grafite">
              {data.status === "erro" ? "A análise falhou. Tente analisar de novo." : "A análise ainda não terminou."}
            </Panel>
          ) : (
            <>
              <Panel className="p-5">
                <ScorePanel score={result.score} criteria={result.criteria} />
              </Panel>
              {result.summary || result.suggestion ? (
                <Panel className="space-y-4 p-5">
                  {result.summary ? (
                    <div>
                      <h2 className="font-bold">Resumo</h2>
                      <p className="mt-1 text-sm leading-relaxed">{result.summary}</p>
                      <p className="mt-1.5 text-xs text-grafite">
                        Etapa: {stageLabel(result.stage)}. Cliente: {sentimentLabel(result.sentiment).toLowerCase()}.
                      </p>
                    </div>
                  ) : null}
                  {result.suggestion ? (
                    <div>
                      <h2 className="flex items-center gap-1.5 font-bold">
                        <Lightbulb aria-hidden size={16} className="text-sinal-forte" />
                        Próxima mensagem sugerida
                      </h2>
                      <p className="mt-2 rounded-[var(--radius-bolha)] rounded-tr-sm bg-bolha-vendedor px-3 py-2 text-sm leading-relaxed">
                        {result.suggestion}
                      </p>
                    </div>
                  ) : null}
                </Panel>
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
              <p className="px-1 text-xs leading-relaxed text-grafite">
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
    <Panel aria-labelledby="alertas-da-conversa" className="p-5">
      <h2 id="alertas-da-conversa" className="font-bold">
        Alertas <span className="numeros font-normal text-grafite">({alerts.length})</span>
      </h2>
      {alerts.length === 0 ? (
        <p className="mt-1 text-sm text-grafite">Nenhum risco ou oportunidade perdida encontrada.</p>
      ) : (
        <ul className="mt-3 space-y-4">
          {alerts.map((alert) => {
            const current = Boolean(alert.message_id) && alert.message_id === selected;
            return (
              <li
                key={alert.id}
                className={`border-l-[3px] pl-3 transition-colors ${current ? "border-tinta" : (STRIPE[alert.severity] ?? "border-linha")}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <SeverityTag severity={alert.severity} />
                  <StatusTag status={alert.status} />
                </div>
                <p className="mt-1.5 text-sm font-bold">{alert.label}</p>
                <p className="mt-0.5 text-sm leading-relaxed text-tinta-suave">{alert.explanation}</p>
                <div className="mt-1.5 flex gap-4 text-sm font-medium">
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
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
