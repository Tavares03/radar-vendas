import { describe, expect, it } from "vitest";

import { formatDateTime, formatScore, relativeTime, severityLabel, statusLabel } from "./format";

describe("formatadores", () => {
  it("nomes em português", () => {
    expect(severityLabel("critico")).toBe("Crítico");
    expect(severityLabel("atencao")).toBe("Atenção");
    expect(statusLabel("falso_positivo")).toBe("Falso positivo");
    expect(statusLabel("em_revisao")).toBe("Em revisão");
  });

  it("nota sem casas decimais e com traço quando não há", () => {
    expect(formatScore(71.4)).toBe("71");
    expect(formatScore(null)).toBe("—");
  });

  it("data e hora no padrão brasileiro", () => {
    expect(formatDateTime("2025-03-11T13:05:00Z", "America/Sao_Paulo")).toBe("11/03/2025 10:05");
  });

  it("tempo relativo", () => {
    const now = new Date("2025-03-11T15:00:00Z");
    expect(relativeTime("2025-03-11T14:58:00Z", now)).toBe("há 2 min");
    expect(relativeTime("2025-03-11T12:00:00Z", now)).toBe("há 3 h");
    expect(relativeTime("2025-03-08T15:00:00Z", now)).toBe("há 3 dias");
  });
});
