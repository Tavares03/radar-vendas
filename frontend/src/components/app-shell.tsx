"use client";

import {
  BookOpenCheck,
  Gauge,
  LogOut,
  MessagesSquare,
  Settings,
  ShieldAlert,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, Suspense } from "react";

import { api } from "@/lib/api/client";
import { can, type Me, useMe } from "@/lib/api/hooks";
import { roleLabel } from "@/lib/format";

import { Loading } from "./ui";

type Item = { href: string; label: string; icon: typeof Gauge; show: (me: Me) => boolean };

const NAV: Item[] = [
  { href: "/", label: "Visão geral", icon: Gauge, show: (me) => can(me, "analisar") },
  { href: "/alertas", label: "Alertas", icon: ShieldAlert, show: () => true },
  { href: "/conversas", label: "Conversas", icon: MessagesSquare, show: () => true },
  { href: "/vendedores", label: "Vendedores", icon: Users, show: (me) => can(me, "analisar") },
  { href: "/playbooks", label: "Playbooks", icon: BookOpenCheck, show: () => true },
  {
    href: "/configuracoes",
    label: "Configurações",
    icon: Settings,
    show: (me) => can(me, "configurar") || can(me, "privacidade"),
  },
];

function active(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

/** Links da navegação; `pathname` nulo enquanto a rota atual ainda não é conhecida. */
function NavLinks({ items, pathname }: { items: Item[]; pathname: string | null }) {
  return (
    <ul className="flex gap-1 md:flex-col">
      {items.map(({ href, label, icon: Icon }) => {
        const current = pathname !== null && active(pathname, href);
        return (
          <li key={href}>
            <Link
              href={href}
              aria-current={current ? "page" : undefined}
              className={`flex items-center gap-2.5 rounded-md px-3 py-2 text-sm whitespace-nowrap ${
                current ? "bg-tinta font-semibold text-papel" : "text-tinta-suave hover:bg-papel hover:text-tinta"
              }`}
            >
              <Icon aria-hidden size={17} strokeWidth={current ? 2.4 : 1.8} />
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function CurrentNavLinks({ items }: { items: Item[] }) {
  return <NavLinks items={items} pathname={usePathname()} />;
}

export function AppShell({ children }: { children: ReactNode }) {
  const { data: me, error } = useMe();
  const router = useRouter();

  async function logout() {
    await api.POST("/api/v1/auth/logout");
    router.replace("/login");
  }

  if (error) {
    return <Loading label="Sua sessão terminou. Abrindo o login…" />;
  }
  if (!me) {
    return <Loading />;
  }
  const items = NAV.filter((item) => item.show(me));

  return (
    <div className="min-h-screen md:grid md:grid-cols-[14rem_1fr]">
      <a
        href="#conteudo"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-folha focus:px-3 focus:py-2"
      >
        Ir para o conteúdo
      </a>
      <aside className="border-b border-linha bg-folha md:sticky md:top-0 md:flex md:h-screen md:flex-col md:border-r md:border-b-0">
        <div className="flex items-center justify-between px-4 py-4 md:block">
          <Link href="/" className="block">
            <span className="block text-lg leading-none font-extrabold tracking-tight">Radar de Vendas</span>
            <span className="mt-1 block text-xs text-grafite">{me.tenant.name}</span>
          </Link>
          <button
            type="button"
            onClick={logout}
            className="rounded-md p-1.5 text-grafite hover:text-tinta md:hidden"
            aria-label="Sair"
          >
            <LogOut size={18} />
          </button>
        </div>
        <nav aria-label="Seções do painel" className="overflow-x-auto px-2 pb-2 [scrollbar-width:none] md:flex-1 md:overflow-visible">
          <Suspense fallback={<NavLinks items={items} pathname={null} />}>
            <CurrentNavLinks items={items} />
          </Suspense>
        </nav>
        <div className="hidden border-t border-linha px-4 py-3 md:block">
          <p className="truncate text-sm font-semibold">{me.name}</p>
          <p className="text-xs text-grafite">{roleLabel(me.role)}</p>
          <button
            type="button"
            onClick={logout}
            className="mt-2 inline-flex items-center gap-1.5 text-sm text-tinta-suave hover:text-tinta"
          >
            <LogOut aria-hidden size={15} /> Sair
          </button>
        </div>
      </aside>
      <main id="conteudo" className="mx-auto w-full max-w-6xl px-4 py-6 md:px-8 md:py-8">
        {children}
      </main>
    </div>
  );
}
