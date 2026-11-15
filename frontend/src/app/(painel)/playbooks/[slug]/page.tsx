import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { PlaybookView } from "./playbook-view";

export const metadata: Metadata = { title: "Playbook" };

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <PlaybookView />
    </Suspense>
  );
}
