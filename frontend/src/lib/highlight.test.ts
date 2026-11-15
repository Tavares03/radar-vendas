import { describe, expect, it } from "vitest";

import { findEvidence, placeholderSpans, segment } from "./highlight";

describe("segment", () => {
  it("separa tarjas de dado pessoal e marcas de evidência", () => {
    const text = "Meu CPF é [CPF], contemplação garantida!";
    const parts = segment(text, [{ type: "CPF", start: 10, end: 15 }], [
      { start: 17, end: 39, severity: "critico", alertId: "a1" },
    ]);
    expect(parts).toEqual([
      { kind: "texto", text: "Meu CPF é " },
      { kind: "tarja", text: "CPF" },
      { kind: "texto", text: ", " },
      { kind: "evidencia", text: "contemplação garantida", severity: "critico", alertIds: ["a1"] },
      { kind: "texto", text: "!" },
    ]);
  });

  it("tarja dentro da evidência continua tarja e a evidência se divide em volta dela", () => {
    const text = "faz o pix pra [PIX] agora";
    const parts = segment(text, [{ type: "PIX", start: 14, end: 19 }], [
      { start: 6, end: 25, severity: "critico", alertId: "a1" },
    ]);
    expect(parts.map((p) => p.kind)).toEqual(["texto", "evidencia", "tarja", "evidencia"]);
    expect(parts[2]).toEqual({ kind: "tarja", text: "PIX", insideEvidence: "critico" });
  });

  it("duas evidências sobrepostas ficam com a severidade mais alta", () => {
    const parts = segment("só hoje, decide agora", [], [
      { start: 0, end: 7, severity: "atencao", alertId: "a" },
      { start: 0, end: 21, severity: "critico", alertId: "b" },
    ]);
    expect(parts[0]).toMatchObject({ kind: "evidencia", severity: "critico", alertIds: ["a", "b"] });
  });

  it("texto sem nada marcado volta inteiro", () => {
    expect(segment("Oi, tudo bem?", [], [])).toEqual([{ kind: "texto", text: "Oi, tudo bem?" }]);
  });
});

describe("placeholderSpans", () => {
  it("acha os marcadores de máscara do Radar e ignora colchetes comuns", () => {
    const text = "Oi [NOME_PESSOA], CPF [CPF] e [nota] [CONTA_BANCARIA]";
    expect(placeholderSpans(text)).toEqual([
      { type: "NOME_PESSOA", start: 3, end: 16 },
      { type: "CPF", start: 22, end: 27 },
      { type: "CONTA_BANCARIA", start: 37, end: 53 },
    ]);
  });
});

describe("findEvidence", () => {
  it("acha o trecho sem diferenciar maiúsculas e acentos", () => {
    expect(findEvidence("Olha, CONTEMPLACAO garantida já", "contemplação garantida")).toEqual({
      start: 6,
      end: 28,
    });
  });

  it("evidência que é a mensagem inteira marca a mensagem toda", () => {
    expect(findEvidence("Achei caro", "Achei caro")).toEqual({ start: 0, end: 10 });
  });

  it("evidência que não aparece não marca nada", () => {
    expect(findEvidence("Oi", "garantido")).toBeNull();
    expect(findEvidence("Oi", "")).toBeNull();
  });
});
