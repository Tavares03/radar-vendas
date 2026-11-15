"use client";

import { CircleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { FIELD } from "@/components/ui";

const INPUT = `${FIELD} py-2.5 text-base`;

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
      <div className="mb-2">
        <h1 id="titulo-login" className="text-[2rem] leading-tight font-extrabold">
          Entrar
        </h1>
        <p className="mt-1.5 text-sm text-grafite">Veja os atendimentos da sua equipe e o que pede atenção agora.</p>
      </div>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        E-mail
        <input name="email" type="email" autoComplete="username" required className={INPUT} />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        Senha
        <input name="password" type="password" autoComplete="current-password" required className={INPUT} />
      </label>
      {error ? (
        <p
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-critico/30 bg-critico-marca/40 px-3 py-2 text-sm"
        >
          <CircleAlert aria-hidden size={16} className="mt-0.5 shrink-0 text-critico" />
          {error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={pending}
        className="mt-1 rounded-lg bg-tinta px-3 py-2.5 font-semibold text-papel shadow-sm transition-colors hover:bg-tinta-suave disabled:opacity-60"
      >
        {pending ? "Entrando…" : "Entrar"}
      </button>
    </form>
  );
}
