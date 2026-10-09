import type { Metadata } from "next";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";

export const metadata: Metadata = {
  title: "GEO-AUDITOR AI | Auditoría de Citabilidad para LLMs",
  description:
    "Sistema avanzado de auditoría GEO/AEO para optimización de citabilidad en ChatGPT, Gemini, Claude y Perplexity.",
  keywords: [
    "GEO",
    "AEO",
    "SEO",
    "LLM optimization",
    "AI citability",
    "ChatGPT",
    "Gemini",
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <body className="min-h-full flex flex-col bg-plane text-ink font-sans">
        <ThemeProvider>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
