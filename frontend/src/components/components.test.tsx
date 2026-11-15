import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Schemas } from "@/lib/api/client";

import { AlertReview } from "./alert-review";
import { MessageBubble } from "./message-bubble";
import { ScorePanel } from "./score-panel";
import { WeeklyTrend } from "./trend";
import { Initials, ScoreBadge, scoreBand, SeverityTag, StatusTag } from "./ui";

type Message = Schemas["MessageOut"];
type Alert = Schemas["AlertOut"];

const TEXT = "Seu CPF [CPF], contemplação garantida!";
const CPF_AT = TEXT.indexOf("[CPF]");
const PROMISE_AT = TEXT.indexOf("contemplação");

function message(overrides: Partial<Message> = {}): Message {
  return {
    id: "m1",
    position: 0,
    sent_at: "2025-03-11T13:05:00Z",
    sender_role: "vendedor",
    sender_key: "k",
    sender_label: "Carla",
    kind: "texto",
    text: TEXT,
    text_available: true,
    revealed: false,
    pii_spans: [{ type: "CPF", start: CPF_AT, end: CPF_AT + 5 }],
    has_audio: false,
    audio_seconds: null,
    transcription_status: "nao_aplicavel",
    edited: false,
    ...overrides,
  };
}

describe("MessageBubble", () => {
  it("mostra dado pessoal como tarja e a evidência com a cor da severidade", () => {
    render(
      <MessageBubble
        message={message()}
        evidence={[
          { start: PROMISE_AT, end: PROMISE_AT + "contemplação garantida".length, severity: "critico", alertId: "a1" },
        ]}
      />,
    );
    expect(screen.getByText("[CPF mascarado]")).toBeInTheDocument();
    expect(screen.queryByText(/\[CPF\]/)).not.toBeInTheDocument();
    const mark = screen.getByText("contemplação garantida");
    expect(mark.tagName).toBe("MARK");
    expect(mark).toHaveAttribute("data-severity", "critico");
  });

  it("vendedor à direita, cliente à esquerda", () => {
    const { container, rerender } = render(<MessageBubble message={message()} />);
    expect(container.firstElementChild).toHaveClass("justify-end");
    rerender(<MessageBubble message={message({ sender_role: "cliente" })} />);
    expect(container.firstElementChild).toHaveClass("justify-start");
  });

  it("áudio transcrito e texto ainda não protegido", () => {
    const { rerender } = render(
      <MessageBubble message={message({ kind: "audio", audio_seconds: 12, pii_spans: [], text: "oi" })} />,
    );
    expect(screen.getByText(/Áudio transcrito, 12 s/)).toBeInTheDocument();
    rerender(<MessageBubble message={message({ text: "", text_available: false })} />);
    expect(screen.getByText("Texto ainda sendo protegido…")).toBeInTheDocument();
  });

  it("texto revelado não ganha tarjas", () => {
    render(<MessageBubble message={message({ revealed: true, text: "CPF 529.982.247-25", pii_spans: [] })} />);
    expect(screen.getByText("CPF 529.982.247-25")).toBeInTheDocument();
  });
});

describe("ScorePanel", () => {
  const criteria = [
    { id: "conformidade", label: "Conformidade", points: 0, maximum: 30, justification: "Promessa indevida.", estimated: false },
    { id: "objecoes", label: "Tratamento de objeções", points: 15, maximum: 20, justification: "1 objeção.", estimated: true },
  ];

  it("mostra a nota, a faixa e de onde vieram os pontos", () => {
    render(<ScorePanel score={42} criteria={criteria} />);
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("Atendimento com problemas")).toBeInTheDocument();
    const meter = screen.getByRole("meter", { name: "Conformidade" });
    expect(meter).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getByText("Promessa indevida.")).toBeInTheDocument();
    expect(screen.getByText("(estimado)")).toBeInTheDocument();
    expect(screen.getByText(/avaliados sem o LLM/)).toBeInTheDocument();
  });
});

describe("AlertReview", () => {
  const alert: Alert = {
    id: "a1",
    conversation_id: "c1",
    message_id: "m1",
    message_index: 1,
    type: "promessa_indevida",
    label: "Promessa indevida",
    category: "risco",
    severity: "critico",
    evidence: "contemplação garantida",
    explanation: "Proibido.",
    sources: {},
    confidence: 1,
    contested: false,
    status: "aberto",
    assigned_to: null,
    review_note: "",
    reviewed_at: null,
    created_at: "2025-03-11T13:05:00Z",
    updated_at: "2025-03-11T13:05:00Z",
    customer_label: "Cliente 7F3A",
    seller_name: "Carla",
  };

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("marca falso positivo pela API e devolve o alerta atualizado", async () => {
    const fetchMock = vi.fn(async (request: Request) =>
      Response.json({ ...alert, status: "falso_positivo" }, { status: request.method === "PATCH" ? 200 : 405 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const onSaved = vi.fn();
    render(<AlertReview alert={alert} users={[]} onSaved={onSaved} />);

    await userEvent.click(screen.getByRole("button", { name: "Falso positivo" }));

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("PATCH");
    expect(new URL(request.url).pathname).toBe("/api/v1/alerts/a1");
    expect(await request.json()).toEqual({ status: "falso_positivo" });
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ status: "falso_positivo" }));
  });

  it("mostra o erro que a API explicou", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ error: { code: "not_found", message: "Alerta não encontrado." } }, { status: 404 })),
    );
    render(<AlertReview alert={alert} users={[]} onSaved={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Alerta não encontrado.");
  });

  it("o status atual fica marcado e desabilitado", () => {
    render(<AlertReview alert={{ ...alert, status: "confirmado" }} users={[]} onSaved={vi.fn()} />);
    const group = screen.getByRole("group", { name: "Mudar o status do alerta" });
    const current = within(group).getByRole("button", { name: "Confirmar" });
    expect(current).toHaveAttribute("aria-pressed", "true");
    expect(current).toBeDisabled();
    expect(within(group).getByRole("button", { name: "Reabrir" })).toBeEnabled();
  });
});

describe("WeeklyTrend", () => {
  const weeks = [
    { week_start: "2026-10-05", conversations: 0, average_score: null, critical_alerts: 0 },
    { week_start: "2026-10-12", conversations: 3, average_score: 71.4, critical_alerts: 1 },
    { week_start: "2026-10-19", conversations: 1, average_score: 88, critical_alerts: 0 },
  ];

  it("descreve cada semana, sem transformar semana vazia em nota zero", () => {
    render(<WeeklyTrend weeks={weeks} />);
    const table = screen.getByRole("table", { name: "Nota média por semana" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("cell")[1].textContent)).toEqual([
      "sem conversas",
      "nota 71 em 3 conversas, 1 alerta crítico em aberto",
      "nota 88 em 1 conversa",
    ]);
  });

  it("mostra a semana em foco para quem navega pelo teclado", async () => {
    render(<WeeklyTrend weeks={weeks} />);
    await userEvent.tab();
    await userEvent.tab();
    expect(screen.getByRole("status")).toHaveTextContent("nota 71 em 3 conversas");
  });

  it("sem nenhuma nota, diz que ainda não há conversas em vez de desenhar um gráfico vazio", () => {
    render(<WeeklyTrend weeks={[weeks[0]]} />);
    expect(screen.getByText(/Ainda não há conversas analisadas/)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("selos", () => {
  it("a régua da nota é a mesma em todo o painel", () => {
    expect([100, 80, 79.9, 60, 59.9, 0].map(scoreBand)).toEqual([
      "ok",
      "ok",
      "atencao",
      "atencao",
      "critico",
      "critico",
    ]);
    expect(scoreBand(null)).toBe("vazio");
    render(<ScoreBadge score={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("severidade e status sempre por extenso, nunca só a cor", () => {
    render(
      <>
        <SeverityTag severity="critico" />
        <StatusTag status="falso_positivo" />
      </>,
    );
    expect(screen.getByText("Crítico")).toBeInTheDocument();
    expect(screen.getByText("Falso positivo")).toBeInTheDocument();
  });

  it("iniciais de quem tem um nome só, dois ou vários", () => {
    const { container } = render(
      <>
        <Initials name="Vera" />
        <Initials name="Vera Nunes" />
        <Initials name="Diego de Souza Farias" />
        <Initials name="Cliente 61F0" />
      </>,
    );
    expect(Array.from(container.children).map((el) => el.textContent)).toEqual(["V", "VN", "DF", "CF"]);
  });
});
