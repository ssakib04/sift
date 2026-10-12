"use client";

import { ReactNode, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { apiRequest, recruiterToken } from "@/lib/api";

function isGuestPath(pathname: string): boolean {
  return pathname.startsWith("/login") || pathname.startsWith("/invite") || pathname.startsWith("/interview");
}

export function RecruiterGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const guest = isGuestPath(pathname);
  const [ready, setReady] = useState(guest);

  useEffect(() => {
    if (isGuestPath(pathname)) {
      setReady(true);
      return;
    }
    setReady(false);
    if (!recruiterToken()) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    let cancelled = false;
    apiRequest("/api/v1/auth/me")
      .then(() => {
        if (!cancelled) {
          setReady(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          router.replace(`/login?next=${encodeURIComponent(pathname)}`);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  if (!ready) {
    return null;
  }
  return <>{children}</>;
}
