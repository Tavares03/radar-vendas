"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

type Me = {
  name: string;
  email: string;
  role: string;
  tenant: { name: string };
};

/** Tela inicial provisória: confirma a sessão e mostra quem entrou. */
export function SessionGate() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    let active = true;
    fetch("/api/v1/auth/me")
      .then(async (response) => {
        if (!active) return;
        if (response.ok) {
          setMe((await response.json()) as Me);
        } else {
          router.replace("/login");
        }
      })
      .catch(() => active && router.replace("/login"));
    return () => {
      active = false;
    };
  }, [router]);

  async function logout() {
    await fetch("/api/v1/auth/logout", { method: "POST" });
    router.replace("/login");
  }

  if (!me) {
    return (
      <main className="flex flex-1 items-center justify-center text-sm text-neutral-500">
        Carregando…
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center gap-4 p-6">
      <h1 className="text-2xl font-semibold">Radar de Vendas</h1>
      <p className="text-neutral-600 dark:text-neutral-300">
        Olá, {me.name}. Você entrou em <strong>{me.tenant.name}</strong> como{" "}
        <strong>{me.role}</strong>.
      </p>
      <button
        type="button"
        onClick={logout}
        className="w-fit rounded-md border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
      >
        Sair
      </button>
    </main>
  );
}
