"use client";

import Link from "next/link";

import { Empty, ErrorNote, Initials, Loading, PageTitle, Panel, ScoreBadge } from "@/components/ui";
import { useOverview, useSellers } from "@/lib/api/hooks";

export function SellersView() {
  const sellers = useSellers();
  const overview = useOverview(180);
  if (sellers.error) return <ErrorNote error={sellers.error} />;
  if (!sellers.data) return <Loading />;
  const stats = new Map((overview.data?.sellers ?? []).map((s) => [s.seller_id, s]));
  // Quem tem a menor nota aparece primeiro; quem ainda não tem conversa analisada vai para o fim.
  const ordered = [...sellers.data].sort((a, b) => {
    const left = stats.get(a.id)?.average_score ?? Number.POSITIVE_INFINITY;
    const right = stats.get(b.id)?.average_score ?? Number.POSITIVE_INFINITY;
    return left - right || a.display_name.localeCompare(b.display_name, "pt-BR");
  });

  return (
    <>
      <PageTitle
        title="Vendedores"
        lead="Nota média, conversas e alertas críticos dos últimos 180 dias. Abra uma pessoa para ver a evolução e os pontos a melhorar."
      />
      {sellers.data.length === 0 ? (
        <Empty title="Nenhum vendedor ainda">
          Os vendedores aparecem quando você importa conversas, ou podem ser cadastrados pela API.
        </Empty>
      ) : (
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[38rem] text-left text-sm">
            <thead className="border-b border-linha text-xs text-grafite">
              <tr>
                <th className="px-4 py-2.5 font-medium">Vendedor</th>
                <th className="px-4 py-2.5 font-medium">Também aparece como</th>
                <th className="px-4 py-2.5 text-right font-medium">Conversas</th>
                <th className="px-4 py-2.5 text-right font-medium">Críticos em aberto</th>
                <th className="px-4 py-2.5 text-right font-medium">Nota média</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-linha">
              {ordered.map((seller) => {
                const stat = stats.get(seller.id);
                return (
                  <tr key={seller.id} className="hover:bg-papel/60">
                    <td className="px-4 py-2.5">
                      <Link
                        href={`/vendedores/${seller.id}`}
                        className="flex items-center gap-2.5 font-semibold hover:underline"
                      >
                        <Initials name={seller.display_name} />
                        {seller.display_name}
                        {!seller.is_active ? <span className="text-xs font-normal text-grafite">inativo</span> : null}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-grafite">{seller.aliases.join(", ") || "—"}</td>
                    <td className="numeros px-4 py-2.5 text-right">{stat?.conversations ?? 0}</td>
                    <td
                      className={`numeros px-4 py-2.5 text-right ${stat?.critical_alerts ? "font-bold text-critico" : "text-grafite"}`}
                    >
                      {stat?.critical_alerts ?? 0}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <ScoreBadge score={stat?.average_score} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Panel>
      )}
    </>
  );
}
