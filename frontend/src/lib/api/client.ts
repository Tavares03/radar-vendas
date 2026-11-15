/**
 * Cliente tipado da API. Os tipos vêm de `schema.d.ts`, gerado do OpenAPI do backend
 * (`npm run api:types`): se a API muda e o painel não acompanha, o `tsc` acusa.
 *
 * O navegador fala só com a própria origem (`/api` é repassado para o backend), com o cookie de
 * sessão httpOnly; nenhum token fica acessível ao JavaScript.
 */
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

export const api = createClient<paths>({
  // Sempre a própria origem: o Next repassa /api para o backend.
  baseUrl: typeof window === "undefined" ? "" : window.location.origin,
  credentials: "same-origin",
  // Resolve o fetch na hora da chamada (não na criação do cliente).
  fetch: (request: Request) => globalThis.fetch(request),
});

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string = "erro",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type ErrorBody = { error?: { code?: string; message?: string } } | undefined;

/** Resultado do openapi-fetch → dado, ou `ApiError` com a mensagem da API. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (response.ok && data !== undefined) return data;
  if (response.status === 401 && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    // Sessão expirada: recarregar a página inteira no login (fora de componente não há router, e
    // a recarga descarta o cache de dados da sessão anterior).
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign("/login");
  }
  const body = error as ErrorBody;
  throw new ApiError(
    body?.error?.message ?? `A API respondeu ${response.status}.`,
    response.status,
    body?.error?.code,
  );
}

/** Para respostas sem corpo (204). */
export async function unwrapEmpty(call: Promise<{ error?: unknown; response: Response }>): Promise<void> {
  const { error, response } = await call;
  if (response.ok) return;
  const body = error as ErrorBody;
  throw new ApiError(body?.error?.message ?? `A API respondeu ${response.status}.`, response.status);
}
