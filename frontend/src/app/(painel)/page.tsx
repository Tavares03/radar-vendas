import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { OverviewView } from "./overview-view";

export const metadata: Metadata = { title: "Visão geral" };

export default function OverviewPage() {
  return (
    <Suspense fallback={<Loading />}>
      <OverviewView />
    </Suspense>
  );
}
