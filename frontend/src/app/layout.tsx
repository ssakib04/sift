import type { Metadata } from "next";
import { Fraunces, Source_Sans_3 } from "next/font/google";
import type { ReactNode } from "react";

import { PersistentChatbot } from "@/components/persistent-chatbot";
import { RecruiterGate } from "@/components/recruiter-gate";

import "./globals.css";

const display = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const ui = Source_Sans_3({
  subsets: ["latin"],
  weight: ["400", "600"],
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
