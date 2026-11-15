import type { Schemas } from "@/lib/api/client";
import { findEvidence, placeholderSpans, type Severity } from "@/lib/highlight";

import { HighlightedText } from "./highlighted-text";

/**
 * A mensagem do alerta com o trecho de evidência marcado. Sem a mensagem (alerta da conversa
 * inteira, ou texto já apagado pela retenção), mostra só a evidência.
 */
export function EvidenceInContext({ alert }: { alert: Schemas["AlertOut"] }) {
  const text = alert.message_text || alert.evidence;
  if (!text) return null;
  const found = findEvidence(text, alert.evidence);
  return (
    <HighlightedText
      text={text}
      pii={placeholderSpans(text)}
      evidence={found ? [{ ...found, severity: alert.severity as Severity, alertId: alert.id }] : []}
    />
  );
}
