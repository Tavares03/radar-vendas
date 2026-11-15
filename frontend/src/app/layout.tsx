import type { Metadata } from "next";
import { Atkinson_Hyperlegible_Next } from "next/font/google";
import "./globals.css";

// Uma família só, desenhada para legibilidade: o painel é lido com atenção, trecho por trecho.
const atkinson = Atkinson_Hyperlegible_Next({
  variable: "--font-atkinson",
  subsets: ["latin"],
  weight: ["400", "500", "700", "800"],
  // A fonte não tem métricas para o fallback ajustado; o fallback é a fonte do sistema.
  adjustFontFallback: false,
});

export const metadata: Metadata = {
  title: {
    default: "Radar de Vendas",
    template: "%s · Radar de Vendas",
  },
  description:
    "Supervisor de vendas com IA para equipes que vendem pelo WhatsApp: riscos, oportunidades e nota de cada atendimento.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="pt-BR" className={`${atkinson.variable} h-full antialiased`}>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
