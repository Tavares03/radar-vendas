"use client";

import {
  BookOpenCheck,
  Gauge,
  LogOut,
  MessagesSquare,
  Settings,
  ShieldAlert,
  Smartphone,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, Suspense } from "react";

import { api } from "@/lib/api/client";
import { can, type Me, useAlerts, useMe } from "@/lib/api/hooks";
import { roleLabel } from "@/lib/format";

import { RadarMark } from "./radar-mark";
import { Initials } from "./ui";

type Item = { href: string; label: string; icon: typeof Gauge; show: (me: Me) => boolean };

const NAV: Item[] = [
  { href: "/", label: "Visão geral", icon: Gauge, show: (me) => can(me, "analisar") },
  { href: "/alertas", label: "Alertas", icon: ShieldAlert, show: () => true },
  { href: "/conversas", label: "Conversas", icon: MessagesSquare, show: () => true },
  { href: "/whatsapp", label: "WhatsApp", icon: Smartphone, show: (me) => can(me, "importar") },
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
function NavLinks({
  items,
  pathname,
  critical,
}: {
  items: Item[];
  pathname: string | null;
  critical: number;
}) {
  return (
    <ul className="flex gap-1 md:flex-col">
      {items.map(({ href, label, icon: Icon }) => {
        const current = pathname !== null && active(pathname, href);
        return (
          <li key={href}>
            <Link
              href={href}
              aria-current={current ? "page" : undefined}
              className={`relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm whitespace-nowrap transition-colors ${
                current
                  ? "bg-noite-suave font-semibold text-white"
                  : "text-nevoa hover:bg-noite-suave/60 hover:text-white"
              }`}
            >
              {current ? (
                <span aria-hidden className="absolute inset-y-2 left-0 hidden w-0.5 rounded-full bg-sinal md:block" />
              ) : null}
              <Icon aria-hidden size={17} strokeWidth={current ? 2.3 : 1.8} className={current ? "text-sinal" : ""} />
              {label}
              {href === "/alertas" && critical > 0 ? (
                <span className="numeros ml-auto rounded-full bg-critico px-1.5 text-[0.7rem] leading-5 font-bold text-white">
                  {critical}
                  <span className="sr-only"> críticos em aberto</span>
                </span>
              ) : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function CurrentNavLinks({ items, critical }: { items: Item[]; critical: number }) {
  return <NavLinks items={items} pathname={usePathname()} critical={critical} />;
}

function NavSkeleton() {
  return (
    <ul aria-hidden className="flex gap-1 md:flex-col">
      {[5, 4, 5, 6].map((width, index) => (
        <li key={index} className="px-3 py-2.5">
          <span className="block h-3.5 animate-brilho rounded bg-noite-suave" style={{ width: `${width}rem` }} />
        </li>
      ))}
    </ul>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  // A casca e a página aparecem juntas: quem ainda não tem sessão é levado ao login pelo 401.
  const { data: me } = useMe();
  const router = useRouter();
  const critical = useAlerts({ severity: "critico", open_only: true, limit: 1 }, Boolean(me));
  const criticalCount = critical.data?.total ?? 0;

  async function logout() {
    await api.POST("/api/v1/auth/logout");
    router.replace("/login");
  }

  const items = me ? NAV.filter((item) => item.show(me)) : [];

  return (
    <div className="min-h-screen md:grid md:grid-cols-[15rem_minmax(0,1fr)]">
      <a
        href="#conteudo"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-folha focus:px-3 focus:py-2"
      >
        Ir para o conteúdo
      </a>
      <aside className="sobre-noite bg-noite text-white md:sticky md:top-0 md:flex md:h-screen md:flex-col">
        <div className="flex items-center justify-between px-4 pt-4 pb-3 md:block md:px-5 md:pt-6 md:pb-5">
          <Link href="/" className="flex items-center gap-2.5 rounded-md">
            <RadarMark size={30} className="text-white" />
            <span>
              <span className="block font-display text-[1.05rem] leading-none font-bold">Radar de Vendas</span>
              <span className="mt-1 block text-xs leading-none text-nevoa">{me?.tenant.name ?? " "}</span>
            </span>
          </Link>
          <button
            type="button"
            onClick={logout}
            className="rounded-md p-1.5 text-nevoa hover:text-white md:hidden"
            aria-label="Sair"
          >
            <LogOut size={18} />
          </button>
        </div>
        <nav
          aria-label="Seções do painel"
          className="overflow-x-auto px-2 pb-2 [scrollbar-width:none] md:flex-1 md:overflow-visible md:px-3"
        >
          {me ? (
            <Suspense fallback={<NavLinks items={items} pathname={null} critical={criticalCount} />}>
              <CurrentNavLinks items={items} critical={criticalCount} />
            </Suspense>
          ) : (
            <NavSkeleton />
          )}
        </nav>
        {me ? (
          <div className="hidden items-center gap-2.5 border-t border-noite-linha px-4 py-4 md:flex">
            <Initials name={me.name} className="bg-noite-suave text-white" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm leading-tight font-semibold">{me.name}</p>
              <p className="text-xs text-nevoa">{roleLabel(me.role)}</p>
            </div>
            <button
              type="button"
              onClick={logout}
              className="rounded-md p-1.5 text-nevoa hover:bg-noite-suave hover:text-white"
              aria-label="Sair"
              title="Sair"
            >
              <LogOut aria-hidden size={17} />
            </button>
          </div>
        ) : null}
      </aside>
      <main id="conteudo" className="mx-auto w-full max-w-[76rem] px-4 py-6 md:px-10 md:py-9">
        {children}
      </main>
    </div>
  );
}
