import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { SellerView } from "./seller-view";

export const metadata: Metadata = { title: "Vendedor" };

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <SellerView />
    </Suspense>
  );
}
