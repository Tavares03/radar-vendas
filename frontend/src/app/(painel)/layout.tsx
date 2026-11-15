import { AppShell } from "@/components/app-shell";

export default function PainelLayout({ children }: LayoutProps<"/">) {
  return <AppShell>{children}</AppShell>;
}
