import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { SettingsView } from "./settings-view";

export const metadata: Metadata = { title: "Configurações" };

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <SettingsView />
    </Suspense>
  );
}
