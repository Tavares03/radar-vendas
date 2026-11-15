import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { SellersView } from "./sellers-view";

export const metadata: Metadata = { title: "Vendedores" };

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <SellersView />
    </Suspense>
  );
}
