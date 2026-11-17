import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { WhatsAppView } from "./whatsapp-view";

export const metadata: Metadata = { title: "WhatsApp" };

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <WhatsAppView />
    </Suspense>
  );
}
