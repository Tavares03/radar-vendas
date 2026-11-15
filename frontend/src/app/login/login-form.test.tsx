import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

import { LoginForm } from "./login-form";

async function fillAndSubmit() {
  await userEvent.type(screen.getByLabelText("E-mail"), "ana@exemplo.com");
  await userEvent.type(screen.getByLabelText("Senha"), "senha-forte-123");
  await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
}

describe("LoginForm", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    replace.mockReset();
  });

  it("entra e vai para o painel", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ access_token: "x" })));
    render(<LoginForm />);
    await fillAndSubmit();
    expect(replace).toHaveBeenCalledWith("/");
  });

  it("mostra a mensagem da API quando a senha está errada", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ error: { code: "invalid_credentials", message: "E-mail ou senha incorretos." } }, { status: 401 }),
      ),
    );
    render(<LoginForm />);
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent("E-mail ou senha incorretos.");
    expect(replace).not.toHaveBeenCalled();
  });

  it("explica quando o servidor não responde", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    render(<LoginForm />);
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent("O servidor não respondeu");
  });
});
