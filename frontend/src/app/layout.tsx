import type { Metadata } from "next";
import { Bricolage_Grotesque, Hanken_Grotesk } from "next/font/google";
import "./globals.css";

// Texto e números: uma grotesca neutra, com algarismos tabulares para as colunas de nota.
const hanken = Hanken_Grotesk({
  variable: "--font-hanken",
  subsets: ["latin"],
});

// Títulos e a nota: uma grotesca com mais caráter, que dá voz ao painel sem atrapalhar a leitura.
const bricolage = Bricolage_Grotesque({
  variable: "--font-bricolage",
  subsets: ["latin"],
  axes: ["opsz"],
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
    <html lang="pt-BR" className={`${hanken.variable} ${bricolage.variable} h-full antialiased`}>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
