import type { Metadata } from "next";
import type { ReactNode } from "react";

import { PersistentChatbot } from "@/components/persistent-chatbot";
import { RecruiterGate } from "@/components/recruiter-gate";

import "./globals.css";

export const metadata: Metadata = {
  title: "Sift",
  description: "AI-powered recruitment platform",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <RecruiterGate>{children}</RecruiterGate>
        <PersistentChatbot />
      </body>
    </html>
  );
}
