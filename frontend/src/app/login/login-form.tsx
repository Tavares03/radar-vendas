"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

const INPUT = "rounded-md border border-linha-forte bg-folha px-3 py-2 text-tinta";

export function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
      });
      if (response.ok) {
        router.replace("/");
        return;
      }
      const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
      setError(body?.error?.message ?? "Não foi possível entrar. Confira o e-mail e a senha.");
    } catch {
      setError("O servidor não respondeu. Verifique se a API está no ar.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex w-full max-w-sm flex-col gap-4" aria-labelledby="titulo-login">
      <div>
        <h1 id="titulo-login" className="text-2xl font-extrabold tracking-tight">
          Radar de Vendas
        </h1>
        <p className="mt-1 text-sm text-grafite">Entre para ver os atendimentos da sua equipe.</p>
      </div>
      <label className="flex flex-col gap-1 text-sm">
        E-mail
        <input name="email" type="email" autoComplete="username" required className={INPUT} />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Senha
        <input name="password" type="password" autoComplete="current-password" required className={INPUT} />
      </label>
      {error ? (
        <p role="alert" className="border-l-4 border-critico pl-3 text-sm">
          {error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={pending}
        className="rounded-md bg-tinta px-3 py-2 text-sm font-semibold text-papel hover:bg-tinta-suave disabled:opacity-60"
      >
        {pending ? "Entrando…" : "Entrar"}
      </button>
    </form>
  );
}
