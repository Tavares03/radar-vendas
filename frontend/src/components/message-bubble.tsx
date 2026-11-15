import { Mic } from "lucide-react";

import type { Schemas } from "@/lib/api/client";
import { formatTime } from "@/lib/format";
import type { EvidenceRange, PiiSpan } from "@/lib/highlight";

import { HighlightedText } from "./highlighted-text";

type Message = Schemas["MessageOut"];

const KIND_TEXT: Record<string, string> = {
  imagem: "imagem",
  video: "vídeo",
  documento: "documento",
  figurinha: "figurinha",
  contato: "contato",
  localizacao: "localização",
  apagada: "mensagem apagada",
  outro: "mídia",
};

/**
 * Uma mensagem no estilo do WhatsApp: cliente à esquerda, vendedor à direita. O texto já vem
 * mascarado da API; com `revealed`, é o original (acesso auditado).
 */
export function MessageBubble({
  message,
  evidence = [],
  highlighted = false,
}: {
  message: Message;
  evidence?: EvidenceRange[];
  highlighted?: boolean;
}) {
  const seller = message.sender_role === "vendedor";
  const pii = (message.pii_spans ?? []) as PiiSpan[];
  const audio = message.kind === "audio";
  let body;
  if (!message.text_available) {
    body = <span className="italic text-grafite">Texto ainda sendo protegido…</span>;
  } else if (message.text) {
    body = <HighlightedText text={message.text} pii={message.revealed ? [] : pii} evidence={evidence} />;
  } else {
    body = <span className="italic text-grafite">{KIND_TEXT[message.kind] ?? "mídia"} sem texto</span>;
  }
  return (
    <div
      id={`m-${message.id}`}
      className={`flex scroll-mt-24 ${seller ? "justify-end" : "justify-start"}`}
    >
      <article
        aria-label={`${seller ? "Vendedor" : "Cliente"} às ${formatTime(message.sent_at)}`}
        className={`max-w-[85%] rounded-[var(--radius-bolha)] px-3.5 py-2 text-[0.95rem] leading-relaxed shadow-[0_1px_0_var(--color-linha)] sm:max-w-[70%] ${
          seller ? "rounded-br-sm bg-bolha-vendedor" : "rounded-bl-sm bg-folha"
        } ${highlighted ? "ring-2 ring-tinta" : ""}`}
      >
        {audio ? (
          <p className="mb-0.5 flex items-center gap-1 text-xs font-medium text-grafite">
            <Mic aria-hidden size={13} /> Áudio transcrito
            {message.audio_seconds ? `, ${Math.round(message.audio_seconds)} s` : ""}
          </p>
        ) : null}
        <p className="whitespace-pre-wrap break-words">{body}</p>
        <p className="mt-0.5 text-right text-[0.7rem] text-grafite">
          {message.edited ? "editada, " : ""}
          {formatTime(message.sent_at)}
        </p>
      </article>
    </div>
  );
}
