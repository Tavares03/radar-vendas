import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { ConversationsView } from "./conversations-view";

export const metadata: Metadata = { title: "Conversas" };

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <ConversationsView />
    </Suspense>
  );
}
