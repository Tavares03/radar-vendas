import { type EvidenceRange, type PiiSpan, segment } from "@/lib/highlight";

const PII_NAMES: Record<string, string> = {
  CPF: "CPF",
  CNPJ: "CNPJ",
  RG: "RG",
  TELEFONE: "telefone",
  EMAIL: "e-mail",
  ENDERECO: "endereço",
  CEP: "CEP",
  PIX: "chave PIX",
  CONTA_BANCARIA: "dado bancário",
  PLACA: "placa",
  NOME_PESSOA: "nome",
};

/** Texto da mensagem com tarjas de dado pessoal e marca-texto nas evidências. */
export function HighlightedText({
  text,
  pii = [],
  evidence = [],
}: {
  text: string;
  pii?: PiiSpan[];
  evidence?: EvidenceRange[];
}) {
  return (
    <>
      {segment(text, pii, evidence).map((part, index) => {
        if (part.kind === "tarja") {
          const name = PII_NAMES[part.text] ?? part.text.toLowerCase();
          return (
            <span key={index} className="tarja" title={`Dado pessoal mascarado: ${name}`}>
              <span className="sr-only">[{name} mascarado]</span>
              <span aria-hidden>{name}</span>
            </span>
          );
        }
        if (part.kind === "evidencia") {
          return (
            <mark key={index} className="evidencia" data-severity={part.severity} data-alerts={part.alertIds.join(" ")}>
              {part.text}
            </mark>
          );
        }
        return <span key={index}>{part.text}</span>;
      })}
    </>
  );
}
