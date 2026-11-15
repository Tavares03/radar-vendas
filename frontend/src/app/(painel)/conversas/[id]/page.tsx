import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { ConversationView } from "./conversation-view";

export const metadata: Metadata = { title: "Conversa" };

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <ConversationView />
    </Suspense>
  );
}
