"use client";

import useSWR, { type SWRConfiguration } from "swr";

import { api, type Schemas, unwrap } from "./client";

const options: SWRConfiguration = { revalidateOnFocus: false, shouldRetryOnError: false };

export type Me = Schemas["MeOut"];

export function useMe() {
  return useSWR<Me>("me", () => unwrap(api.GET("/api/v1/auth/me")), options);
}

export function useOverview(days: number, enabled = true) {
  return useSWR(enabled ? ["overview", days] : null, () =>
    unwrap(api.GET("/api/v1/overview", { params: { query: { days } } })),
  options);
}

export type AlertFilters = {
  status?: Schemas["AlertStatus"];
  severity?: string;
  type?: string;
  seller_id?: string;
  conversation_id?: string;
  open_only?: boolean;
  limit?: number;
  offset?: number;
};

export function useAlerts(filters: AlertFilters) {
  return useSWR(["alerts", filters], () =>
    unwrap(api.GET("/api/v1/alerts", { params: { query: filters } })),
  options);
}

export type ConversationFilters = {
  seller_id?: string;
  status?: Schemas["ConversationStatus"];
  needs_review?: boolean;
  limit?: number;
  offset?: number;
};

export function useConversations(filters: ConversationFilters) {
  return useSWR(["conversations", filters], () =>
    unwrap(api.GET("/api/v1/conversations", { params: { query: filters } })),
  { ...options, refreshInterval: (data) =>
      data?.items.some((c) => c.status === "pendente" || c.status === "processando") ? 3000 : 0 });
}

export function useConversation(id: string | undefined, reveal: boolean) {
  return useSWR(id ? ["conversation", id, reveal] : null, () =>
    unwrap(
      api.GET("/api/v1/conversations/{conversation_id}", {
        params: { path: { conversation_id: id as string }, query: { reveal } },
      }),
    ),
  options);
}

export function useAnalysis(id: string | undefined) {
  return useSWR(id ? ["analysis", id] : null, () =>
    unwrap(
      api.GET("/api/v1/conversations/{conversation_id}/analysis", {
        params: { path: { conversation_id: id as string } },
      }),
    ),
  options);
}

export function useSellers() {
  return useSWR("sellers", () => unwrap(api.GET("/api/v1/sellers")), options);
}

export function useSellerPerformance(id: string | undefined) {
  return useSWR(id ? ["seller-performance", id] : null, () =>
    unwrap(
      api.GET("/api/v1/sellers/{seller_id}/performance", {
        params: { path: { seller_id: id as string } },
      }),
    ),
  options);
}

export function useUsers(enabled: boolean) {
  return useSWR(enabled ? "users" : null, () => unwrap(api.GET("/api/v1/users")), options);
}

/** Quem pode receber um alerta (nome e papel), para quem revisa. */
export function useAssignees(enabled: boolean) {
  return useSWR(enabled ? "assignees" : null, () => unwrap(api.GET("/api/v1/alerts/assignees")), options);
}

export function usePlaybooks() {
  return useSWR("playbooks", () => unwrap(api.GET("/api/v1/playbooks")), options);
}

export function usePlaybook(slug: string | undefined) {
  return useSWR(slug ? ["playbook", slug] : null, () =>
    unwrap(api.GET("/api/v1/playbooks/{slug}", { params: { path: { slug: slug as string } } })),
  options);
}

const PERMISSION = {
  revisar: "alerts:review",
  revelar: "pii:reveal",
  gerir: "users:manage",
  analisar: "analytics:read",
  playbooks: "playbooks:write",
  privacidade: "privacy:manage",
  configurar: "settings:manage",
} as const;

/** O que o usuário pode fazer, pelas permissões que a própria API informa em `/auth/me`. */
export function can(me: Me | undefined, action: keyof typeof PERMISSION): boolean {
  return Boolean(me?.permissions.includes(PERMISSION[action]));
}
