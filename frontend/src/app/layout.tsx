import type { Metadata } from "next";
import type { ReactNode } from "react";

import { PersistentChatbot } from "@/components/persistent-chatbot";

import "./globals.css";

export const metadata: Metadata = {
  title: "Sift",
  description: "AI-powered recruitment platform",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        {children}
        <PersistentChatbot />
      </body>
    </html>
  );
}
