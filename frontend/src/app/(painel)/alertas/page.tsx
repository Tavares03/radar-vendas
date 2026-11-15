import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { AlertsView } from "./alerts-view";

export const metadata: Metadata = { title: "Alertas" };

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <AlertsView />
    </Suspense>
  );
}
