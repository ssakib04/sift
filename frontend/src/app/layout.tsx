import type { Metadata } from "next";
import localFont from "next/font/local";
import type { ReactNode } from "react";

import { PersistentChatbot } from "@/components/persistent-chatbot";
import { RecruiterGate } from "@/components/recruiter-gate";

import "./globals.css";

const display = localFont({
  src: [
    { path: "../fonts/fraunces-latin-400.woff2", weight: "400", style: "normal" },
    { path: "../fonts/fraunces-latin-500.woff2", weight: "500", style: "normal" },
    { path: "../fonts/fraunces-latin-600.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-display",
  display: "swap",
});

const ui = localFont({
  src: [
    { path: "../fonts/source-sans-3-latin-400.woff2", weight: "400", style: "normal" },
    { path: "../fonts/source-sans-3-latin-600.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-ui",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Sift",
  description: "AI-powered recruitment platform",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${ui.variable}`}>
      <body className="bg-umber font-sans text-ivory antialiased">
        <RecruiterGate>{children}</RecruiterGate>
        <PersistentChatbot />
      </body>
    </html>
  );
}
