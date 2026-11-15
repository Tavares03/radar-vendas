"use client";

import Link from "next/link";

import { Empty, ErrorNote, Loading, PageTitle } from "@/components/ui";
import { useOverview, useSellers } from "@/lib/api/hooks";
import { formatScore } from "@/lib/format";

export function SellersView() {
  const sellers = useSellers();
  const overview = useOverview(180);
  if (sellers.error) return <ErrorNote error={sellers.error} />;
  if (!sellers.data) return <Loading />;
  const stats = new Map((overview.data?.sellers ?? []).map((s) => [s.seller_id, s]));

  return (
    <>
      <PageTitle title="Vendedores" />
      {sellers.data.length === 0 ? (
        <Empty title="Nenhum vendedor ainda">
          Os vendedores aparecem quando você importa conversas, ou podem ser cadastrados pela API.
        </Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <thead className="border-b border-linha-forte text-grafite">
              <tr>
                <th className="py-2 font-medium">Vendedor</th>
                <th className="py-2 font-medium">Também aparece como</th>
                <th className="py-2 text-right font-medium">Conversas (180 dias)</th>
                <th className="py-2 text-right font-medium">Nota média</th>
                <th className="py-2 text-right font-medium">Críticos em aberto</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-linha">
              {sellers.data.map((seller) => {
                const stat = stats.get(seller.id);
                return (
                  <tr key={seller.id}>
                    <td className="py-2.5">
                      <Link href={`/vendedores/${seller.id}`} className="font-semibold hover:underline">
                        {seller.display_name}
                      </Link>
                      {!seller.is_active ? <span className="ml-2 text-xs text-grafite">inativo</span> : null}
                    </td>
                    <td className="py-2.5 text-grafite">{seller.aliases.join(", ") || "—"}</td>
                    <td className="numeros py-2.5 text-right">{stat?.conversations ?? 0}</td>
                    <td className="numeros py-2.5 text-right font-semibold">{formatScore(stat?.average_score)}</td>
                    <td className={`numeros py-2.5 text-right ${stat?.critical_alerts ? "font-semibold text-critico" : "text-grafite"}`}>
                      {stat?.critical_alerts ?? 0}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
