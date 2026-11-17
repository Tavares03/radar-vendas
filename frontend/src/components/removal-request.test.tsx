import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Schemas } from "@/lib/api/client";

import { RemovalRequestBox } from "./removal-request";

type Removal = Schemas["RemovalRequestOut"];

const pending: Removal = {
  id: "r1",
  conversation_id: "c1",
  conversation_label: "Cliente 7F3A com Carla, 12 mensagens",
  seller: { id: "s1", display_name: "Carla" },
  requested_by: "Carla Mendes",
  reason: "Conversa pessoal, é minha mãe.",
  status: "pendente",
  decided_by: "",
  decided_at: null,
  decision_note: "",
  created_at: "2026-11-16T12:00:00Z",
};

function box(overrides: Partial<Parameters<typeof RemovalRequestBox>[0]> = {}) {
  return (
    <RemovalRequestBox
      conversationId="c1"
      live={false}
      pending={null}
      canRequest
      canDecide={false}
      onChanged={vi.fn()}
      onRemoved={vi.fn()}
      {...overrides}
    />
  );
}

describe("RemovalRequestBox", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("o vendedor só pede, com motivo, e não vê botão de apagar", async () => {
    const fetchMock = vi.fn<(request: Request) => Promise<Response>>(async () => Response.json(pending, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const onChanged = vi.fn();
    render(box({ onChanged }));

    expect(screen.queryByRole("button", { name: /aprovar/i })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /pedir remoção/i }));
    const send = screen.getByRole("button", { name: "Enviar pedido" });
    expect(send).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox"), "Conversa pessoal");
    await userEvent.click(send);

    const request = fetchMock.mock.calls[0][0];
    expect(new URL(request.url).pathname).toBe("/api/v1/conversations/c1/removal-request");
    expect(await request.json()).toEqual({ reason: "Conversa pessoal" });
    expect(onChanged).toHaveBeenCalled();
  });

  it("com o pedido pendente, o vendedor só vê que está esperando a gestão", () => {
    render(box({ pending }));

    expect(screen.getByText(/até a gestão decidir/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("a gestão aprova e, numa conversa ao vivo, para de capturar o contato", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi.fn<(request: Request) => Promise<Response>>(async () =>
      Response.json({ ...pending, status: "aprovado" }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const onRemoved = vi.fn();
    render(box({ pending, live: true, canDecide: true, onRemoved }));

    expect(screen.getByRole("checkbox", { name: /parar de capturar/i })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: /aprovar e apagar/i }));

    const request = fetchMock.mock.calls[0][0];
    expect(new URL(request.url).pathname).toBe("/api/v1/removal-requests/r1/approve");
    expect(await request.json()).toEqual({ note: "", stop_capturing: true });
    expect(onRemoved).toHaveBeenCalled();
  });

  it("quem pode apagar direto não vê o botão de pedir", () => {
    render(box({ canDecide: true }));

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
