import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { PlaybooksView } from "./playbooks-view";

export const metadata: Metadata = { title: "Playbooks" };

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <PlaybooksView />
    </Suspense>
  );
}
